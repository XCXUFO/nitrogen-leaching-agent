"use client";

import { createContext, useContext, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { initialDemoPapers, initialDemoTags, type DemoPaper, type DemoTag } from "@/lib/showcase-literature";

const Store = createContext<{
  papers: DemoPaper[]; setPapers: Dispatch<SetStateAction<DemoPaper[]>>;
  tags: DemoTag[]; setTags: Dispatch<SetStateAction<DemoTag[]>>; reset: () => void;
} | null>(null);

export function ShowcaseLiteratureProvider({ children }: { children: ReactNode }) {
  const [papers, setPapers] = useState(initialDemoPapers);
  const [tags, setTags] = useState(initialDemoTags);
  const [version, setVersion] = useState(0);
  return <Store.Provider key={version} value={{ papers, setPapers, tags, setTags, reset: () => { setPapers(initialDemoPapers); setTags(initialDemoTags); setVersion((old) => old + 1); } }}>{children}</Store.Provider>;
}

export function useShowcaseLiterature() {
  const value = useContext(Store);
  if (!value) throw new Error("Showcase literature provider is required");
  return value;
}
