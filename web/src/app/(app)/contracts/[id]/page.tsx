"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, fmtDate, won } from "@/lib/api";
import { useStandardFields } from "@/lib/hooks";
import type { Contract, Doc, ValidationResult } from "@/lib/types";
import ContractForm from "@/components/ContractForm";
import { Badge, Button, Card, CardHeader, Empty, ErrorText, FlowSteps, Loading, Modal, PageHeader } from "@/components/ui";
import AddDocumentPanel from "@/components/workspace/AddDocumentPanel";
import MailModal from "@/components/workspace/MailModal";
import ValidationPanel from "@/components/workspace/ValidationPanel";

export default function ContractWorkspace() {
  const { id } = useParams<{ id: string }>();
  const cid = Number(id);
  const router = useRouter();
  const { labelOf } = useStandardFields();

  const [contract, setContract] = useState<Contract | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [withAi, setWithAi] = useState(false);
  const [validating, setValidating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [mailOpen, setMailOpen] = useState(false);
  const [error, setError] = useState("");

  const loadDocs = useCallback(() => api.get<Doc[]>(`/contracts/${cid}/documents`).then(setDocs), [cid]);

  useEffect(() => {
    api.get<Contract>(`/contracts/${cid}`).then(setContract).catch((e) => setError(e.message));
    loadDocs();
  }, [cid, loadDocs]);

  const addDocument = async (templateId: number, projectCode = "") => {
    setError("");
    try {
      await api.post(`/contracts/${cid}/documents`, { template_id: templateId, project_code: projectCode });
      setResult(null);
      await loadDocs();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const removeDoc = async (d: Doc) => {
    if (!confirm(`'${d.title}' 서류를 삭제할까요?`)) return;
    await api.del(`/documents/${d.id}`);
    setResult(null);
    loadDocs();
  };

  const runValidate = async () => {
    setValidating(true);
    try {
      setResult(await api.post<ValidationResult>(`/contracts/${cid}/validate?with_ai=${withAi}`));
      loadDocs();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setValidating(false);
    }
  };

  const exportZip = async (format: string) => {
    setExporting(true);
    try {
      await api.download(`/contracts/${cid}/export?format=${format}`, "제출서류.zip");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  };

  const deleteContract = async () => {
    if (!confirm("이 계약과 작성한 서류를 모두 삭제할까요? 되돌릴 수 없습니다.")) return;
    await api.del(`/contracts/${cid}`);
    router.replace("/dashboard");
  };

  if (error && !contract) return <ErrorText>{error}</ErrorText>;
  if (!contract) return <Loading />;

  const step = docs.length === 0 ? 0 : result?.summary.ready_for_submission ? 4 : result ? 3 : 2;

  return (
    <>
      <PageHeader
        back={{ href: "/dashboard", label: "내 계약" }}
        title={contract.contract_title}
        desc={contract.client_name ? `발주처: ${contract.client_name}` : undefined}
        action={
          <>
            <Button variant="secondary" onClick={() => setEditOpen(true)}>
              계약정보 수정
            </Button>
            <Button variant="danger" onClick={deleteContract}>
              삭제
            </Button>
          </>
        }
      />

      <Card className="mb-5">
        <div className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
          <Info label="계약금액" value={contract.amount ? won(contract.amount) : "-"} />
          <Info label="계약일자" value={fmtDate(contract.contract_date)} />
          <Info label="착수일" value={fmtDate(contract.start_date)} />
          <Info label="완료일" value={fmtDate(contract.end_date)} />
        </div>
        <div className="border-t border-line px-5 py-3">
          <FlowSteps current={Math.min(step, 3)} />
        </div>
      </Card>

      <ErrorText>{error}</ErrorText>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="제출 서류" desc="서류를 추가하면 회사·계약정보가 자동으로 채워집니다." action={<Badge tone="indigo">{docs.length}건</Badge>} />
            {docs.length === 0 ? (
              <Empty title="아직 추가된 서류가 없습니다" desc="오른쪽에서 요청받은 서류를 검색하거나 기업 양식을 업로드하세요." />
            ) : (
              <ul className="divide-y divide-line">
                {docs.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Link href={`/contracts/${cid}/documents/${d.id}`} className="font-medium hover:text-primary">
                          {d.title}
                        </Link>
                        <Badge tone={d.template_kind === "builtin" ? "gray" : "blue"}>{d.template_kind === "builtin" ? "기본 양식" : d.template_kind === "custom" ? "맞춤 초안" : "자체 양식"}</Badge>
                        <Badge tone="indigo">{d.output_format === "xlsx" ? "Excel" : d.output_format === "hwpx" ? "한글" : d.output_format === "pdf" ? "PDF" : "Word"}</Badge>
                        {d.status === "reviewed" ? <Badge tone="green">검토 완료</Badge> : <Badge tone="amber">작성 중</Badge>}
                      </div>
                      <div className="mt-0.5 text-xs text-muted">
                        {d.missing.length > 0 ? (
                          <span className="text-red-500">빈 항목 {d.missing.length}개: {d.missing.map(labelOf).join(", ")}</span>
                        ) : (
                          `항목 ${d.field_keys.length}개 모두 입력됨`
                        )}
                      </div>
                    </div>
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="secondary" onClick={() => router.push(`/contracts/${cid}/documents/${d.id}`)}>
                        편집·미리보기
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => api.download(`/documents/${d.id}/download?format=native`, `${d.title}.${d.output_format}`)}>
                        {d.output_format === "xlsx" ? "Excel" : d.output_format === "hwpx" ? "한글" : d.output_format === "pdf" ? "PDF" : "Word"}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => removeDoc(d)} aria-label="삭제">
                        ✕
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {result && <ValidationPanel result={result} contractId={cid} />}
        </div>

        <div className="space-y-5">
          <AddDocumentPanel contractId={cid} clientName={contract.client_name} onAdd={addDocument} onDocumentsChanged={async () => { setResult(null); await loadDocs(); }} onChecklistChanged={() => setResult(null)} />

          <Card>
            <CardHeader title="검토 · 제출" />
            <div className="space-y-3 p-4">
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={withAi} onChange={(e) => setWithAi(e.target.checked)} />
                <span>
                  AI 문장 검토 포함
                  <span className="block text-xs text-muted">마스킹 후 필요한 텍스트만 전송 (API 키 설정 시)</span>
                </span>
              </label>
              <Button className="w-full" onClick={runValidate} loading={validating}>
                제출 전 통합 점검 실행
              </Button>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="secondary" onClick={() => exportZip("native")} loading={exporting} disabled={docs.length === 0}>
                  원본 ZIP
                </Button>
                <Button variant="secondary" onClick={() => exportZip("pdf")} loading={exporting} disabled={docs.length === 0}>
                  PDF ZIP
                </Button>
              </div>
              <Button variant="secondary" className="w-full" onClick={() => setMailOpen(true)} disabled={docs.length === 0}>
                메일 제출
              </Button>
              {result && !result.summary.passed && <p className="text-xs text-red-500">검토에서 오류가 발견되었습니다. 수정 후 다시 검토하세요.</p>}
            </div>
          </Card>
        </div>
      </div>

      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="계약정보 수정">
        <ContractForm
          initial={contract}
          submitLabel="저장"
          onSubmit={async (v) => {
            setContract(await api.put<Contract>(`/contracts/${cid}`, v));
            await loadDocs();
            setEditOpen(false);
            setResult(null);
          }}
        />
        <p className="mt-3 text-xs text-muted">저장하면 기존 서류의 빈 항목과 자동 입력된 계약정보도 갱신됩니다. 서류에서 직접 수정한 값은 유지됩니다.</p>
      </Modal>

      {mailOpen && <MailModal onClose={() => setMailOpen(false)} contractId={cid} docs={docs} />}
    </>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs text-muted">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}
