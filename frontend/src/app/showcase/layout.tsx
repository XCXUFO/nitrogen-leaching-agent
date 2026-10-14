import { ShowcaseLiteratureProvider } from "@/components/showcase-literature-provider";

export default function ShowcaseLayout({ children }: { children: React.ReactNode }) {
  return <ShowcaseLiteratureProvider>{children}</ShowcaseLiteratureProvider>;
}
