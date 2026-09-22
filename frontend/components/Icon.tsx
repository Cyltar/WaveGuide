import type { SVGProps } from "react";

export type IconName = "wave" | "menu" | "close" | "chat" | "history" | "send" | "chart" | "search" | "team" | "build";

const paths: Record<IconName, React.ReactNode> = {
  wave: <><path d="M2 13c4 0 5-9 10-9s6 9 10 9"/><path d="M2 18c4 0 6-9 10-9s6 9 10 9"/><path d="M2 22c4 0 6-8 10-8s6 8 10 8"/></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  chat: <path d="M5 4h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-6 3V6a2 2 0 0 1 2-2Z"/>,
  history: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 3"/></>,
  send: <><path d="m21 3-7 18-4-7-7-4L21 3Z"/><path d="m10 14 6-6"/></>,
  chart: <><path d="M4 20V12h3v8M11 20V4h3v16M18 20V9h3v11"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  team: <><circle cx="12" cy="8" r="3"/><path d="M6 21v-3a6 6 0 0 1 12 0v3M4 4a3 3 0 0 0 0 6M20 4a3 3 0 0 1 0 6M2 18v-2a4 4 0 0 1 2-3M22 18v-2a4 4 0 0 0-2-3"/></>,
  build: <><path d="m12 2 9 5v10l-9 5-9-5V7l9-5ZM3 7l9 5 9-5M12 12v10"/></>,
};

export default function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
