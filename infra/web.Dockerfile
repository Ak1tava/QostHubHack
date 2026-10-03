FROM node:24.19.0-bookworm-slim AS build
WORKDIR /workspace/apps/web
RUN npm install --global npm@12.2.0
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
COPY packages/contracts/ /workspace/packages/contracts/
RUN npm run build

FROM nginx:stable-alpine
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/web/dist /usr/share/nginx/html
EXPOSE 80
