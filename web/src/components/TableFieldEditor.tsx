"use client";

import { Button, Input, Textarea } from "./ui";

export default function TableFieldEditor({ columns, value, onChange, disabled = false, id }: {
  columns: string[]; value: string; onChange: (value: string) => void; disabled?: boolean; id: string;
}) {
  const rows = value ? value.split("\n").filter(line => line.trim()).map(line => line.split("|")) : [columns.map(() => "")];
  // Preserve malformed legacy rows for explicit correction rather than dropping cells.
  const invalid = rows.some(row => row.length !== columns.length);
  const update = (next: string[][]) => onChange(next.map(row => row.join("|")).join("\n"));
  return <div id={id} tabIndex={-1} className="space-y-2">
    {invalid ? <><p role="alert" className="text-xs text-amber-800">기존 입력의 열 수가 다릅니다. {columns.length}개 열로 맞추면 칸 편집이 열립니다.</p><Textarea aria-label="표 원문 수정" value={value} onChange={e => onChange(e.target.value)} disabled={disabled} /></> : <>
      <div className="overflow-x-auto"><table className="w-full border-collapse text-xs"><thead><tr>{columns.map((column, i) => <th key={i} scope="col" className="border border-line p-2 text-left">{column}</th>)}<th scope="col" className="border border-line p-1">행 관리</th></tr></thead>
        <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((column, colIndex) => <td key={colIndex} className="min-w-[110px] border border-line p-1"><Input aria-label={`${rowIndex + 1}행 ${column}`} maxLength={500} disabled={disabled} value={row[colIndex] ?? ""} onChange={e => {
          const next = rows.map(item => [...item]); next[rowIndex][colIndex] = e.target.value.replace(/[|\r\n]/g, " "); update(next);
        }} /></td>)}<td className="border border-line p-1"><Button type="button" size="sm" variant="ghost" aria-label={`${rowIndex + 1}행 삭제`} disabled={disabled} onClick={() => update(rows.filter((_, i) => i !== rowIndex))}>삭제</Button></td></tr>)}</tbody></table></div>
      <Button type="button" size="sm" variant="secondary" disabled={disabled || rows.length >= 50} onClick={() => update([...rows, columns.map(() => "")])}>행 추가 ({rows.length}/50)</Button>
    </>}
  </div>;
}
