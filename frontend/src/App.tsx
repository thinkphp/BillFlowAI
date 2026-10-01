import { ChangeEvent, DragEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownUp, ArrowRight, Check, CheckCircle2, CircleHelp, Clock3,
  FileCheck2, FileText, Filter, LoaderCircle, Plus, Search, ShieldCheck, Sparkles,
  Upload, X,
} from "lucide-react";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const TRACKED = ["supplier_name", "supplier_tax_id", "invoice_number", "issue_date", "due_date", "currency", "subtotal", "tax_amount", "other_charges", "previous_balance", "total_amount"];

type LineItem = { description: string; quantity: number | null; unit_price: number | null; tax_rate: number | null; amount: number | null };
type InvoiceData = {
  supplier_name: string | null; supplier_tax_id: string | null; invoice_number: string | null;
  issue_date: string | null; due_date: string | null; currency: string | null;
  subtotal: number | null; tax_amount: number | null; other_charges: number | null; previous_balance: number | null; total_amount: number | null; line_items: LineItem[];
};
type Invoice = {
  id: number; filename: string; status: "needs_review" | "validated"; data: InvoiceData;
  confidence: Record<string, number>; uncertain_fields: string[]; validation_errors: string[];
  created_at: string; updated_at: string;
};

const fieldLabels: Record<string, string> = {
  supplier_name: "Supplier", supplier_tax_id: "Tax ID", invoice_number: "Invoice number",
  issue_date: "Issue date", due_date: "Due date", currency: "Currency",
  subtotal: "Subtotal", tax_amount: "Tax", other_charges: "Additional charges / adjustments", previous_balance: "Previous balance", total_amount: "Total due",
};

function fieldsWithValidationIssues(errors: string[]): Set<string> {
  const fields = new Set<string>();
  for (const error of errors) {
    const message = error.toLowerCase();
    if (message.includes("total") && message.includes("subtotal")) {
      fields.add("subtotal");
      fields.add("tax_amount");
      fields.add("other_charges");
      fields.add("previous_balance");
      fields.add("total_amount");
    }
    if (message.includes("line item sum")) fields.add("subtotal");
    if (message.includes("due date") && message.includes("issue date")) {
      fields.add("issue_date");
      fields.add("due_date");
    }
  }
  return fields;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? "Something went wrong. Please try again.");
  }
  return response.json() as Promise<T>;
}

function formatMoney(value: number | null, currency: string | null) {
  if (value === null) return "—";
  try {
    return new Intl.NumberFormat("en-GB", { style: "currency", currency: currency || "RON" }).format(value);
  } catch {
    return `${new Intl.NumberFormat("en-GB", { minimumFractionDigits: 2 }).format(value)} ${currency ?? ""}`.trim();
  }
}

function App() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "needs_review" | "validated">("all");
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const loadInvoices = useCallback(async () => {
    try {
      setInvoices(await request<Invoice[]>("/api/invoices"));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The API is unavailable.");
    }
  }, []);

  useEffect(() => { void loadInvoices(); }, [loadInvoices]);

  const visible = useMemo(() => invoices.filter((invoice) => {
    const matchesFilter = filter === "all" || invoice.status === filter;
    const term = search.toLocaleLowerCase("en");
    const matchesSearch = !term || [invoice.filename, invoice.data.supplier_name, invoice.data.invoice_number]
      .some((value) => value?.toLocaleLowerCase("en").includes(term));
    return matchesFilter && matchesSearch;
  }), [filter, invoices, search]);
  const reviewCount = invoices.filter((invoice) => invoice.status === "needs_review").length;
  const total = invoices.reduce((sum, invoice) => sum + (invoice.data.total_amount ?? 0), 0);
  const currencies = new Set(invoices.map((invoice) => invoice.data.currency).filter(Boolean));
  const hasUnknownCurrency = invoices.some((invoice) => !invoice.data.currency);
  const processedTotal = !invoices.length ? formatMoney(0, "RON") :
    currencies.size === 1 && !hasUnknownCurrency
      ? formatMoney(total, [...currencies][0])
      : "Mixed currencies";
  const todayLabel = new Intl.DateTimeFormat("en-GB", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  }).format(new Date()).toLocaleUpperCase("en-GB");

  async function upload(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Please choose a PDF document.");
      return;
    }
    setUploading(true);
    setError("");
    setNotice("");
    const form = new FormData();
    form.append("file", file);
    try {
      const invoice = await request<Invoice>("/api/invoices", { method: "POST", body: form });
      setInvoices((previous) => [invoice, ...previous]);
      setSelected(invoice);
      setNotice("Invoice processed. Review the highlighted fields before confirming.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The invoice could not be processed.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void upload(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void upload(file);
  }

  async function saveInvoice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    setSaving(true);
    const form = new FormData(event.currentTarget);
    const data: Record<string, string | number | null> = {};
    TRACKED.forEach((field) => {
      const value = String(form.get(field) ?? "").trim();
      data[field] = field.endsWith("_date") ? (value || null) :
        ["subtotal", "tax_amount", "other_charges", "previous_balance", "total_amount"].includes(field) ? (value ? Number(value) : null) :
          (value || null);
    });
    try {
      const updated = await request<Invoice>(`/api/invoices/${selected.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
      });
      setSelected(updated);
      setInvoices((previous) => previous.map((invoice) => invoice.id === updated.id ? updated : invoice));
      setNotice(updated.status === "validated" ? "Invoice validated. All required fields are complete." : "Your changes have been saved.");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Your changes could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="app-shell" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
      <main className="main">
        <header className="topbar">
          <div className="brand"><span className="brand-mark"><FileCheck2 size={19} /></span><span>BillFlow<span className="brand-light">AI</span></span></div>
          <div className="top-actions"><div className="secure-tag"><ShieldCheck size={17} /> Your data is secure</div><span className="user-chip"><span>AM</span> Alex</span></div>
        </header>

        <div className="page-content">
          <section className="welcome-row">
            <div><div className="eyebrow"><span className="live-dot" /> {todayLabel}</div><h1>Invoices, minus <span>the busywork.</span></h1><p>Drop them in. Let AI sort the details. You stay in control.</p></div>
          </section>

          {error && <div className="alert error-alert"><X size={17} /><span>{error}</span><button onClick={() => setError("")}><X size={16} /></button></div>}
          {notice && <div className="alert success-alert"><CheckCircle2 size={17} /><span>{notice}</span><button onClick={() => setNotice("")}><X size={16} /></button></div>}

          <section className={`upload-card ${dragging ? "dragging" : ""}`} onDragEnter={() => setDragging(true)} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
            <div className="upload-art" aria-hidden="true"><span className="art-orbit orbit-one" /><span className="art-orbit orbit-two" /><span className="art-spark">✳</span><FileText size={36} /></div>
            <div className="upload-copy"><div className="upload-kicker"><Sparkles size={15} /> SMART EXTRACTION</div><strong>{uploading ? "Reading your invoice..." : dragging ? "Nice. Drop it here." : "Start with an invoice"}</strong><p>{uploading ? "AI is reading the document and checking the totals." : "Upload a PDF and turn its details into data you can review."}</p><div className="upload-meta"><span><Check size={14} /> PDF, up to 15 MB</span><i /> <span>Your documents stay private</span></div></div>
            <button className="primary-button" onClick={() => fileRef.current?.click()} disabled={uploading}>{uploading ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}{uploading ? "Processing..." : "Choose a PDF"} {!uploading && <ArrowRight size={16} />}</button>
          </section>
          <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={onFileChange} />

          <section className="stats-grid">
            <article className="stat-card"><span className="stat-icon blue"><FileText size={19} /></span><div><small>Invoices processed</small><strong>{invoices.length}</strong></div></article>
            <article className="stat-card"><span className="stat-icon amber"><Clock3 size={19} /></span><div><small>Needs your review</small><strong>{reviewCount}</strong></div></article>
            <article className="stat-card"><span className="stat-icon green"><ArrowDownUp size={19} /></span><div><small>Total invoice value</small><strong className="stat-amount">{processedTotal}</strong></div></article>
            <div className="stats-note"><Sparkles size={17} /><span>AI handles the busywork.<br /><b>You stay in control.</b></span></div>
          </section>

          <section className="table-section">
            <div className="table-heading"><div><div className="section-eyebrow">YOUR WORKSPACE</div><h2>All invoices <span>{invoices.length}</span></h2><p>Everything in one place. Uncertain fields are flagged for review.</p></div><button className="text-button" onClick={() => fileRef.current?.click()}><Plus size={17} /> Add invoice</button></div>
            <div className="table-toolbar">
              <div className="tabs"><button className={filter === "all" ? "selected" : ""} onClick={() => setFilter("all")}>All <span>{invoices.length}</span></button><button className={filter === "needs_review" ? "selected" : ""} onClick={() => setFilter("needs_review")}>Needs review <span>{reviewCount}</span></button><button className={filter === "validated" ? "selected" : ""} onClick={() => setFilter("validated")}>Approved <span>{invoices.length - reviewCount}</span></button></div>
              <div className="table-tools"><label className="search-box"><Search size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search invoices..." /></label><button className="tool-button"><Filter size={17} /> Filter</button><button className="tool-button sort-button" aria-label="Sort invoices"><ArrowDownUp size={17} /></button></div>
            </div>
            <div className="table-wrap"><table><thead><tr><th>DOCUMENT</th><th>SUPPLIER</th><th>INVOICE NO.</th><th>ISSUE DATE</th><th>AMOUNT</th><th>STATUS</th><th></th></tr></thead><tbody>
              {visible.map((invoice) => <tr key={invoice.id} onClick={() => { setSelected(invoice); setNotice(""); }}>
                <td><div className="file-cell"><span className="pdf-icon"><FileText size={18} /></span><span><strong>{invoice.filename}</strong><small>PDF · {new Date(invoice.created_at).toLocaleDateString("en-GB")}</small></span></div></td>
                <td>{invoice.data.supplier_name || <span className="muted">Unknown</span>}</td><td>{invoice.data.invoice_number || <span className="muted">—</span>}</td>
                <td>{invoice.data.issue_date ? new Date(`${invoice.data.issue_date}T00:00:00`).toLocaleDateString("en-GB") : "—"}</td>
                <td className="amount-cell">{formatMoney(invoice.data.total_amount, invoice.data.currency)}</td>
                <td><span className={`status ${invoice.status}`}><i />{invoice.status === "validated" ? "Approved" : `${invoice.uncertain_fields.length || invoice.validation_errors.length ? "Needs review" : "Processing"}`}</span></td><td><button className="row-action" aria-label="Open invoice"><ArrowRight size={18} /></button></td>
              </tr>)}
              {!visible.length && <tr><td colSpan={7}><div className="empty-state"><div className="empty-icon"><FileText size={25} /></div><strong>{invoices.length ? "No invoices found" : "Your invoice space is ready"}</strong><p>{invoices.length ? "Try another search or change the selected filter." : "Upload your first PDF to start extracting invoice details automatically."}</p>{!invoices.length && <button className="secondary-button" onClick={() => fileRef.current?.click()}><Plus size={17} /> Upload your first invoice</button>}</div></td></tr>}
            </tbody></table></div>
            <div className="table-footer"><span>Showing <strong>{visible.length}</strong> of <strong>{invoices.length}</strong> invoices</span><button className="pagination-button" disabled>Previous</button><button className="pagination-button" disabled>Next <ArrowRight size={15} /></button></div>
          </section>
          <footer><span><Sparkles size={15} /> Made for invoices, built for people.</span><span>Review extracted data before using it for accounting.</span></footer>
        </div>
      </main>

      {selected && <div className="drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}>
        <section className="review-drawer">
          <header className="drawer-header"><div><div className="drawer-eyebrow"><Sparkles size={15} /> AI EXTRACTION</div><h2>Review invoice</h2><p>{selected.filename}</p></div><button className="icon-button" onClick={() => setSelected(null)} aria-label="Close"><X size={19} /></button></header>
          <div className="drawer-body">
            <div className={`review-banner ${selected.status}`}><span className="review-banner-icon">{selected.status === "validated" ? <CheckCircle2 size={20} /> : <CircleHelp size={20} />}</span><div><strong>{selected.status === "validated" ? "Invoice approved" : "A quick review is needed"}</strong><p>{selected.status === "validated" ? "All fields are complete and the totals passed validation." : `${selected.uncertain_fields.length} uncertain fields${selected.validation_errors.length ? ` · ${selected.validation_errors.length} validation issues` : ""}. Confirm or correct the values below.`}</p></div></div>
            {!!selected.validation_errors.length && <div className="validation-errors"><strong>Fix the highlighted fields</strong><p className="validation-help">Click an amount below, enter the correct value from the PDF, then choose “Save changes”.</p>{selected.validation_errors.map((item) => <p className="validation-message" key={item}><X size={15} />{item}</p>)}</div>}
            <form id="review-form" onSubmit={saveInvoice}>
              <div className="form-section-title"><span>INVOICE DETAILS</span><small><Sparkles size={14} /> AI suggestion</small></div>
              {TRACKED.map((field) => {
                const value = selected.data[field as keyof InvoiceData];
                const text = value === null || value === undefined ? "" : String(value);
                const uncertain = selected.uncertain_fields.includes(field);
                const hasValidationIssue = fieldsWithValidationIssues(selected.validation_errors).has(field);
                const confidence = selected.confidence[field];
                const numeric = ["subtotal", "tax_amount", "other_charges", "previous_balance", "total_amount"].includes(field);
                const nonNegative = ["subtotal", "tax_amount", "previous_balance", "total_amount"].includes(field);
                return <label key={field} className={`field-wrap ${uncertain ? "uncertain" : ""} ${hasValidationIssue ? "validation-issue" : ""}`}><span>{fieldLabels[field]}{hasValidationIssue && <em>Check amount</em>}{uncertain && !hasValidationIssue && <em>Check this value</em>}</span><div className="input-with-confidence"><input name={field} type={field.endsWith("_date") ? "date" : numeric ? "number" : "text"} step={numeric ? "0.01" : undefined} min={nonNegative ? "0" : undefined} defaultValue={text} placeholder="Not found" aria-invalid={hasValidationIssue} /><small className={confidence < 0.75 ? "low-confidence" : ""}>{confidence === undefined ? "—" : `${Math.round(confidence * 100)}%`}</small></div></label>;
              })}
              {!!selected.data.line_items?.length && <div className="line-items"><div className="form-section-title"><span>LINE ITEMS</span></div>{selected.data.line_items.map((item, index) => <div className="line-item" key={`${item.description}-${index}`}><span>{item.description || "Untitled line item"}<small>{item.quantity ?? "—"} × {formatMoney(item.unit_price, selected.data.currency)}</small></span><strong>{formatMoney(item.amount, selected.data.currency)}</strong></div>)}</div>}
            </form>
          </div>
          <div className="drawer-footer"><button className="secondary-button" type="button" onClick={() => setSelected(null)}>Close</button><button className="primary-button" type="submit" form="review-form" disabled={saving}>{saving ? <LoaderCircle className="spin" size={17} /> : <Check size={18} />}{saving ? "Saving..." : selected.status === "validated" ? "Save changes" : "Confirm and save"}</button></div>
        </section>
      </div>}
    </div>
  );
}

export default App;
