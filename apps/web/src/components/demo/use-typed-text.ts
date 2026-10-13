// From the interactive-product-demo skill (MIT, (c) 2026 Nouman Sarwar): github.com/noumansarwarr/interactive-product-demo
'use client';

import * as React from 'react';

interface TypedTextOptions {
  /** Reveal whole lines instead of characters — a markdown table sliced
   *  mid-row parses as a paragraph and reflows once the rest arrives. */
  byLine?: boolean;
  /** ms per revealed unit */
  ms: number;
  /** false parks the reveal at nothing, so a beat that has not started (or has
   *  already committed) shows no partial text. */
  running: boolean;
}

/** The visible prefix of `text`, one unit longer every `ms` while `running`.
 *  Use for chat replies, AI console output, terminal lines, search-as-you-type. */
export function useTypedText(
  text: string,
  { byLine, ms, running }: TypedTextOptions,
): string {
  const units = React.useMemo(() => {
    if (!byLine) return Array.from(text);
    // A table header and its `| --- |` separator have to land in the same step:
    // on its own the header parses as a paragraph of raw pipes.
    return text.split('\n').reduce<string[]>((out, line) => {
      if (out.length && /^\s*\|[\s:|-]+\|\s*$/.test(line))
        out[out.length - 1] += `\n${line}`;
      else out.push(line);
      return out;
    }, []);
  }, [byLine, text]);
  const [count, setCount] = React.useState(0);

  // (SyncCut) reset happens in the cleanup and the result is gated on `running`,
  // instead of a synchronous setState at the top of the effect (React Compiler lint).
  React.useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(
      () => setCount((n) => Math.min(units.length, n + 1)),
      ms,
    );
    return () => {
      window.clearInterval(timer);
      setCount(0);
    };
  }, [ms, running, units]);

  return running ? units.slice(0, count).join(byLine ? '\n' : '') : '';
}
