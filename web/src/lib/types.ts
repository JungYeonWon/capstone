export type User = { id: number; email: string; name: string };

export type Company = {
  seal_image: string;
  seal_size_mm: number;
  has_seal: boolean;
  company_name: string;
  representative: string;
  business_number: string;
  address: string;
  phone: string;
  email: string;
  manager_name: string;
  business_type: string;
  business_item: string;
  bank_name: string;
  account_number: string;
  account_holder: string;
};

export type Contract = {
  id: number;
  contract_title: string;
  client_name: string;
  amount: number;
  contract_date: string | null;
  start_date: string | null;
  end_date: string | null;
  description: string;
  created_at: string;
  document_count: number;
};

export type FieldLocation = { type: "cell" | "para" | "pdf_line" | "pdf_rect" | "hwpx_cell" | "hwpx_para" | "hwpx_placeholder"; [k: string]: unknown };

export type TemplateField = {
  label: string;
  field_key: string | null;
  confidence: number;
  method: "rule" | "ai" | "user";
  context: string;
  location: FieldLocation;
};

export type CustomPlanSection = { key: string; label: string; kind: "text" | "table"; columns: string[]; required: boolean };
export type DocumentType = "free" | "work_plan" | "proposal" | "report" | "pledge";
export type CustomPlanLayout = { title: string; sections: CustomPlanSection[]; document_type?: DocumentType };

export type Template = {
  custom_plan?: { layout: CustomPlanLayout; request: string; reference: string; unofficial: boolean; version?: number; root_id?: number; parent_id?: number; version_note?: string } | null;
  owner_id: number | null;
  library: LibraryMetadata;
  id: number;
  kind: "builtin" | "uploaded" | "custom";
  name: string;
  category: string;
  description: string;
  aliases: string[];
  fields: TemplateField[];
  field_keys: string[];
  source_type: "docx" | "pdf" | "hwp" | "hwpx" | null;
  output_format: "hwpx" | "xlsx" | "docx" | "pdf";
  status: "analyzing" | "ready" | "archived" | "review_pending";
  expires_at: string | null;
  created_at: string;
};

export type LibraryMetadata = {
  scope: "common" | "organization" | "private";
  organization?: string;
  document_type?: string;
  source_url?: string | null;
  source_date?: string | null;
  version?: string;
  project_code?: string;
  usage_terms?: string;
  review_note?: string;
  reviewed_at?: string;
};

export type StandardField = { key: string; label: string; group: string; synonyms: string[] };

export type Doc = {
  id: number;
  contract_id: number;
  template_id: number;
  title: string;
  values: Record<string, string>;
  status: "draft" | "reviewed";
  template_kind: "builtin" | "uploaded" | "custom";
  output_format: "hwpx" | "xlsx" | "docx" | "pdf";
  field_keys: string[];
  missing: string[];
  updated_at: string;
};

export type Issue = {
  severity: "error" | "warning";
  type: string;
  field_key: string | null;
  field_label: string | null;
  message: string;
  document_ids: number[];
  document_titles: string[];
};

export type ValidationResult = {
  summary: { documents: number; errors: number; warnings: number; passed: boolean; ready_for_submission?: boolean };
  issues: Issue[];
  ai_comments: { document_id: number; title: string; comments: string[] }[];
};

export type UploadAnalysis = {
  title: string;
  detected: number;
  mapped: number;
  ai_used: boolean;
  masked: Record<string, number>;
  sent_chars: number;
  mode: string;
};
