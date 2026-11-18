import { PublicFooter } from "../../components/layout/PublicFooter";
import { PublicHeader } from "../../components/layout/PublicHeader";

export default function PublicLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="public-layout"><PublicHeader /><main>{children}</main><PublicFooter /></div>;
}
