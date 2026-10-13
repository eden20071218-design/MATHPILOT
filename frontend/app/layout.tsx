import "./globals.css";
import {Workspace} from '../components/workspace';

export const metadata = { title: "MathPilot", description: "个性化数学学习规划" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body><Workspace>{children}</Workspace></body></html>;
}

