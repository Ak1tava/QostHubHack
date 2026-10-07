"""Issuing masters may add at most five private before photos to their own draft issuance."""
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import func, select

from conftest import sign_in
from test_photos import photo_client, upload
from work_order_helpers import add_user, seed_order


def master_upload(client, order, token, **changes):
    return upload(client, order['id'], token, type='before', expected_version=order['version'],
                  assignment_version=1, **changes)


def test_master_before_photo_is_private_and_exact_retry_is_deduplicated(photo_client, database):
    from app.modules.work_orders.models import Photo
    order = seed_order(database)
    token = sign_in(photo_client, 'master')
    first = master_upload(photo_client, order, token)
    assert first.status_code == 201, first.text
    second = master_upload(photo_client, order, token)
    assert second.status_code == 201
    assert second.json()['id'] == first.json()['id']
    photo = database['session'].get(Photo, UUID(first.json()['id']))
    assert photo.uploaded_by == database['master'].id
    assert photo_client.get(first.json()['read_url']).status_code == 200
    assert database['session'].scalar(select(func.count()).select_from(Photo)) == 1


@pytest.mark.parametrize('status', ['ACCEPTED', 'QUEUED', 'IN_PROGRESS', 'PAUSED', 'REWORK', 'CLOSED', 'CANCELLED'])
def test_master_photo_is_frozen_after_issuance(photo_client, database, status):
    order = seed_order(database, status)
    response = master_upload(photo_client, order, sign_in(photo_client, 'master'))
    assert response.status_code == 409, response.text


@pytest.mark.parametrize('changes,expected', [({'expected_version': '2'}, 409),
                                            ({'assignment_version': '2'}, 409), ({}, 422)])
def test_master_upload_requires_current_order_and_assignment_versions(photo_client, database, changes, expected):
    order = seed_order(database)
    data = {'expected_version': '1', 'assignment_version': '1', **changes} if changes else {}
    response = upload(photo_client, order['id'], sign_in(photo_client, 'master'), type='before', **data)
    assert response.status_code == expected, response.text


def test_other_master_same_area_and_master_after_photo_are_forbidden(photo_client, database):
    add_user(database, 'other-master', role='master')
    order = seed_order(database)
    response = master_upload(photo_client, order, sign_in(photo_client, 'other-master'))
    assert response.status_code == 403
    response = upload(photo_client, order['id'], sign_in(photo_client, 'master'), type='after',
                      expected_version=1, assignment_version=1)
    assert response.status_code == 403


def test_inaccessible_issuing_master_photo_returns_404(photo_client, database):
    from app.modules.auth.models import UserArea
    order = seed_order(database)
    db = database['session']
    db.delete(db.get(UserArea, (database['master'].id, database['area'].id)))
    db.commit()
    assert master_upload(photo_client, order, sign_in(photo_client, 'master')).status_code == 404


def test_sixth_master_photo_is_rejected_without_changing_existing_evidence(photo_client, database, tmp_path):
    from app.modules.work_orders.models import Photo
    order = seed_order(database)
    token = sign_in(photo_client, 'master')
    for index in range(6):
        output = BytesIO()
        Image.new('RGB', (32, 24), color=(index * 35, 20, 50)).save(output, format='JPEG')
        response = master_upload(photo_client, order, token, content=output.getvalue())
        assert response.status_code == (201 if index < 5 else 422), response.text
    assert database['session'].scalar(select(func.count()).select_from(Photo)) == 5
    assert len(list(tmp_path.iterdir())) == 5


def submitted_report(database, order):
    from app.modules.catalog.models import WorkCode
    from app.modules.work_orders.models import Submission, WorkOrder
    db = database['session']
    report = Submission(work_order_id=UUID(order['id']), revision=1, assignment_version=1,
                        worker_id=database['worker'].id, work_description='Проверен насос',
                        work_code_id=db.scalar(select(WorkCode.id)), no_materials_used=True)
    db.add(report)
    db.commit()
    return db.get(WorkOrder, UUID(order['id'])), report


def test_uploaded_worker_photo_is_readable_by_ai_after_metadata_stripping(photo_client, database, tmp_path):
    from app.modules.ai_review.inputs import build_input, read_images
    from app.modules.work_orders.models import Photo
    from test_photos import image_bytes
    order = seed_order(database)
    response = upload(photo_client, order['id'], sign_in(photo_client),
                      content=image_bytes(size=(300, 240), exif=True))
    assert response.status_code == 201
    saved, report = submitted_report(database, order)
    photo = database['session'].get(Photo, UUID(response.json()['id']))
    photo.submission_id = report.id
    database['session'].commit()
    value = build_input(database['session'], saved, report)
    checked, images = read_images(database['session'], report, value, tmp_path)
    assert f'photo:{photo.id}' in images
    assert checked.photo_refs[0]['quality'] != 'unusable'


def test_issuance_photos_are_in_worker_detail_and_actual_ai_input(photo_client, client, database, tmp_path):
    from app.modules.ai_review.inputs import build_input, read_images
    from test_photos import image_bytes
    order = seed_order(database)
    response = master_upload(photo_client, order, sign_in(photo_client, 'master'),
                             content=image_bytes(size=(300, 240), exif=True))
    assert response.status_code == 201
    sign_in(client)
    detail = client.get(f"/api/v1/work-orders/{order['id']}")
    assert detail.status_code == 200
    assert [photo['id'] for photo in detail.json()['issuance_photos']] == [response.json()['id']]
    saved, report = submitted_report(database, order)
    value = build_input(database['session'], saved, report)
    assert [photo['id'] for photo in value.photo_refs] == [f"photo:{response.json()['id']}"]
    _, images = read_images(database['session'], report, value, tmp_path)
    assert f"photo:{response.json()['id']}" in images
