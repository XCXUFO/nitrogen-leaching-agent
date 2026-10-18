"use client";

import { createContext, useContext, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { initialDemoPapers, initialDemoTags, type DemoPaper, type DemoTag } from "@/lib/showcase-literature";
import { initialDemoCases, initialDemoQuestions, type DemoCase, type DemoQuestion, type DemoReceipt } from "@/lib/showcase-workbench";

const Store = createContext<{
  papers: DemoPaper[]; setPapers: Dispatch<SetStateAction<DemoPaper[]>>;
  tags: DemoTag[]; setTags: Dispatch<SetStateAction<DemoTag[]>>; reset: () => void;
  cases: DemoCase[]; setCases: Dispatch<SetStateAction<DemoCase[]>>;
  questions: DemoQuestion[]; setQuestions: Dispatch<SetStateAction<DemoQuestion[]>>;
  receipts: DemoReceipt[]; setReceipts: Dispatch<SetStateAction<DemoReceipt[]>>;
} | null>(null);

export function ShowcaseLiteratureProvider({ children }: { children: ReactNode }) {
  const [papers, setPapers] = useState(initialDemoPapers);
  const [tags, setTags] = useState(initialDemoTags);
  const [version, setVersion] = useState(0);
  const [cases, setCases] = useState(initialDemoCases);
  const [questions, setQuestions] = useState(initialDemoQuestions);
  const [receipts, setReceipts] = useState<DemoReceipt[]>([]);
  return <Store.Provider key={version} value={{ papers, setPapers, tags, setTags, cases, setCases, questions, setQuestions, receipts, setReceipts, reset: () => {
    setPapers(initialDemoPapers); setTags(initialDemoTags); setCases(initialDemoCases); setQuestions(initialDemoQuestions); setReceipts([]); setVersion((old) => old + 1);
  } }}>{children}</Store.Provider>;
}

export function useShowcaseLiterature() {
  const value = useContext(Store);
  if (!value) throw new Error("Showcase literature provider is required");
  return value;
}
