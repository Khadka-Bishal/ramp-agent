interface Props {
  diff: string;
}

export default function DiffViewer({ diff }: Props) {
  if (!diff.trim()) {
    return <div className="empty"><p>No diff.</p></div>;
  }

  const lines = diff.split('\n');
  const occurrences = new Map<string, number>();
  const keyedLines = lines.map((line) => {
    const next = (occurrences.get(line) ?? 0) + 1;
    occurrences.set(line, next);
    return { line, key: `${line}:${next}` };
  });

  return (
    <div className="diff">
      {keyedLines.map(({ line, key }, i) => (
        <div key={key} className={`diff-line ${classify(line)}`}>
          <span style={{ color: 'var(--text-3)', userSelect: 'none', display: 'inline-block', width: '3ch', textAlign: 'right', marginRight: '0.75rem' }}>
            {i + 1}
          </span>
          {line}
        </div>
      ))}
    </div>
  );
}

function classify(line: string): string {
  if (line.startsWith('@@')) return 'diff-hunk';
  if (line.startsWith('+')) return 'diff-add';
  if (line.startsWith('-')) return 'diff-del';
  return 'diff-ctx';
}
