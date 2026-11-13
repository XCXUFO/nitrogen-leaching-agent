"use client";

import { useEffect, useRef, useState } from "react";
import { Popover } from "@base-ui/react/popover";
import styles from "./literature-table-tags.module.css";

type TableTag = { id: string; label: string };

export function LiteratureTableTags({ tags }: { tags: TableTag[] }) {
  const [open, setOpen] = useState(false);
  const [capacity, setCapacity] = useState(1);
  const trigger = useRef<HTMLButtonElement>(null);
  const hasTags = tags.length > 0;

  useEffect(() => {
    const element = trigger.current;
    if (!element) return;
    // The trigger fills the cell without contributing to the row's height.
    // Recalculate when other columns, fonts, or viewport changes resize the row.
    const observer = new ResizeObserver(([entry]) => {
      const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight);
      if (lineHeight > 0) setCapacity(Math.max(1, Math.floor((entry.contentRect.height + 0.5) / lineHeight)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasTags]);

  const visibleCount = Math.min(capacity, tags.length);
  if (!tags.length) return <span className="text-muted-foreground">未打标（全局）</span>;

  return <Popover.Root open={open} onOpenChange={setOpen} modal={false}>
    <Popover.Trigger ref={trigger} openOnHover delay={160} closeDelay={120} className={styles.trigger}
      aria-label={`查看全部 ${tags.length} 个标签`}
      onFocus={(event) => { if (event.currentTarget.matches(":focus-visible")) setOpen(true); }}>
      <span className={styles.summary}>{tags.slice(0, visibleCount).map(tag => <span key={tag.id} className={styles.line}>{tag.label}</span>)}</span>
      {tags.length > visibleCount && <span className={styles.count}>+{tags.length - visibleCount}</span>}
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Positioner side="bottom" align="start" sideOffset={8} collisionPadding={12}
        className={`evaluation-workspace ${styles.positioner}`}>
        <Popover.Popup aria-label="文献全部标签" initialFocus={false} finalFocus={false} className={styles.popup}>
          <ul className={styles.tags}>
            {tags.map(tag => <li key={tag.id} className={styles.tag}>{tag.label}</li>)}
          </ul>
        </Popover.Popup>
      </Popover.Positioner>
    </Popover.Portal>
  </Popover.Root>;
}
