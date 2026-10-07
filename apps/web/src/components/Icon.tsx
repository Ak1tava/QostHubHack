const paths = {
  tool: 'M14 6a5 5 0 0 0-6 6L3 17a2.8 2.8 0 0 0 4 4l5-5a5 5 0 0 0 6-6l-4 3-3-3Z',
  shift: 'M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z',
  report: 'M4 3v17h17M8 15v-5m5 5V6m5 9V9',
  telegram: 'm3 10 18-7-6 18-4-8-8-3Zm8 3 10-10',
  plus: 'M12 5v14M5 12h14',
  calendar: 'M7 3v4m10-4v4M3 11h18M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z',
  list: 'M8 5h12M8 12h12M8 19h12M4 5h.01M4 12h.01M4 19h.01',
} as const;

export function Icon({ name }: { name: keyof typeof paths }) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d={paths[name]} /></svg>;
}
