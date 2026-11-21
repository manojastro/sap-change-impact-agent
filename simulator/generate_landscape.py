"""SAP-LIKE landscape generator (simulation only - no real SAP system).

Seeds a deterministic, DB-backed synthetic S/4HANA-like estate:
business processes, steps, transactions, Fiori apps, custom ABAP objects,
configuration items, tables/fields, interfaces, batch jobs, roles, regression
test cases (with historical stats), dependency graph edges, defect seeds for
the validation simulation, and a couple of sample transports.

Idempotent: seed_landscape() wipes and rebuilds the estate tables.
"""
from __future__ import annotations

import sys
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

from sqlalchemy.orm import Session  # noqa: E402

from backend.app import models as m  # noqa: E402

SIMULATION_LABEL = "SAP-LIKE SIMULATION (synthetic data, no real SAP system or license)"


def _wipe(db: Session) -> None:
    meta = m.Base.metadata
    tables = [
        "tool_calls", "evaluation_runs", "metric_snapshots",
        "cloud_alm_release_plans", "cloud_alm_defects", "cloud_alm_executions",
        "cloud_alm_test_links", "cloud_alm_tasks", "cloud_alm_features",
        "defects", "outcomes", "test_executions", "validations",
        "approvals", "risk_assessments", "test_selections", "impact_results",
        "actions", "hypotheses", "evidence", "stage_runs", "analyses",
        "transport_objects", "transports", "graph_edges", "events", "defect_seeds",
        "test_cases", "roles", "batch_jobs", "interfaces", "table_fields",
        "tables", "config_items", "custom_code", "fiori_apps", "transactions",
        "process_steps", "processes",
    ]
    for name in tables:
        if name in meta.tables:
            db.execute(meta.tables[name].delete())
    db.commit()


def seed_landscape(db: Session) -> dict:
    _wipe(db)

    # ------------------------------------------------------------- processes
    p_o2c = m.Process(code="ORDER_TO_CASH", name="Order to Cash", module="SD",
                      criticality="CRITICAL", owner="sd-lead",
                      description="Quote to cash: order entry, delivery, billing, accounting release.")
    p_p2p = m.Process(code="PROCURE_TO_PAY", name="Procure to Pay", module="MM",
                      criticality="HIGH", owner="mm-lead",
                      description="Requisition to payment: PO lifecycle, goods receipt, invoice.")
    p_r2r = m.Process(code="RECORD_TO_REPORT", name="Record to Report", module="FI",
                      criticality="HIGH", owner="fi-controller",
                      description="Journal posting, FX valuation, reconciliation, closing.")
    p_htr = m.Process(code="HIRE_TO_RETIRE", name="Hire to Retire", module="HR",
                      criticality="MEDIUM", owner="hr-lead",
                      description="Payroll simulation and posting for the workforce.")
    p_im = m.Process(code="INVENTORY_MANAGEMENT", name="Inventory Management", module="MM",
                     criticality="MEDIUM", owner="wh-lead",
                     description="Stock counts, nightly stock sync, stock overview.")
    db.add_all([p_o2c, p_p2p, p_r2r, p_htr, p_im])
    db.flush()

    def step(code, proc, seq, name, desc=""):
        return m.ProcessStep(code=code, process_id=proc.id, sequence=seq, name=name, description=desc)

    steps = {
        "SO_ENTRY": step("STEP_O2C_SO_CREATE", p_o2c, 10, "Enter Sales Order"),
        "DELIVERY": step("STEP_O2C_DELIVER", p_o2c, 20, "Create Outbound Delivery"),
        "BILLING": step("STEP_O2C_BILLING", p_o2c, 30, "Create Billing Document"),
        "ACC_RELEASE": step("STEP_O2C_ACC_RELEASE", p_o2c, 40, "Release Billing to Accounting"),
        "PO_CREATE": step("STEP_P2P_PO_CREATE", p_p2p, 10, "Create Purchase Order"),
        "PO_APPROVE": step("STEP_P2P_PO_RELEASE", p_p2p, 20, "Release / Approve Purchase Order"),
        "PO_RECEIVE": step("STEP_P2P_PO_RECEIVE", p_p2p, 30, "Post Goods Receipt"),
        "PO_INVOICE": step("STEP_P2P_PO_INVOICE", p_p2p, 40, "Enter Vendor Invoice"),
        "GL_POST": step("STEP_R2R_GL_POST", p_r2r, 10, "Post Manual Journal Entry"),
        "FX_RUN": step("STEP_R2R_FX_REVAL", p_r2r, 20, "Run Foreign Currency Valuation"),
        "FI_RECON": step("STEP_R2R_FI_RECON", p_r2r, 30, "Run Finance Reconciliation"),
        "PAYROLL_SIM": step("STEP_HTR_PAYROLL_SIM", p_htr, 10, "Payroll Simulation Dry-Run"),
        "STOCK_COUNT": step("STEP_IM_STOCK_COUNT", p_im, 10, "Enter Physical Inventory Count"),
        "STOCK_VIEW": step("STEP_IM_STOCK_OVERVIEW", p_im, 20, "Stock Overview Report"),
    }
    db.add_all(steps.values())
    db.flush()

    # ------------------------------------------------------------ transactions
    tx_defs = [
        ("SO_CREATE", "Create Sales Order", "SD"), ("SO_DELIVER", "Create Delivery", "SD"),
        ("BILLING_CREATE", "Create Billing Document", "SD"), ("GL_POST", "Post General Journal Entry", "FI"),
        ("PO_CREATE", "Create Purchase Order", "MM"), ("PO_RELEASE", "Release Purchase Order", "MM"),
        ("PO_RECEIVE", "Post Goods Receipt", "MM"), ("PO_INVOICE", "Enter Vendor Invoice", "MM"),
        ("FX_REVALUATE", "Foreign Currency Valuation", "FI"), ("FI_RECONCILE_RUN", "Start FI Reconciliation Run", "FI"),
        ("PAYROLL_SIMULATE", "Payroll Simulation", "HR"), ("STOCK_COUNT_ENTRY", "Physical Inventory Count Entry", "MM"),
        ("STOCK_OVERVIEW", "Stock Overview", "MM"), ("DUNNING_RUN", "Dunning Proposal Run", "FI"),
        ("MATERIAL_DOC_DISPLAY", "Display Material Document", "MM"), ("AC_DOCUMENT_DISPLAY", "Display Accounting Document", "FI"),
    ]
    txs = {}
    for code, name, mod in tx_defs:
        t = m.Transaction(code=code, name=name, module=mod)
        db.add(t)
        txs[code] = t
    db.flush()

    # ------------------------------------------------------------- fiori apps
    fiori = [
        ("FIORI_ORDER_TRACK", "My Sales Orders"), ("FIORI_BILLING", "Billing Management"),
        ("FIORI_MY_PO", "Approve Purchase Orders"), ("FIORI_GL_DASHBOARD", "GL Account Dashboard"),
        ("FIORI_STOCK_OVERVIEW", "Stock Overview Tile"), ("FIORI_PAYROLL_SIM", "Payroll Simulation Tile"),
    ]
    fios = {}
    for code, name in fiori:
        f = m.FioriApp(code=code, name=name)
        db.add(f)
        fios[code] = f
    db.flush()

    # ------------------------------------------------------------ custom code
    cc_defs = [
        ("Z_PRICING_DETERMINATION_EXIT", "USER_EXIT", "Pricing determination exit used by sales order entry and billing."),
        ("Z_ORDER_VALIDATION_BADI", "BADI", "Order intake validation BAdI (availability & credit check hooks)."),
        ("Z_MM_STOCK_SYNC_REPORT", "REPORT", "Nightly stock synchronisation report from receipts/issues."),
        ("Z_FI_RECONCILIATION_JOB", "REPORT", "Finance reconciliation between subledger and GL balances."),
        ("Z_FX_REVALUATION_REPORT", "REPORT", "Foreign currency open-item valuation postings."),
        ("Z_PO_RELEASE_WORKFLOW", "WORKFLOW", "Multi-level PO release workflow with value-based strategy."),
        ("Z_PO_OUTPUT_PROGRAM", "PROGRAM", "Emits purchase order output to the vendor portal channel."),
        ("Z_INVOIC_OUTPUT_PROGRAM", "PROGRAM", "Builds outbound customer invoices payload from billing documents."),
        ("Z_PAYMENT_MATCHING_INBOUND", "PROGRAM", "Matches inbound bank payment statements to open invoices."),
        ("Z_PAYROLL_SCHEMA_EXIT", "USER_EXIT", "Custom payroll schema rule exit for allowances."),
    ]
    ccs = {}
    for name, ctype, desc in cc_defs:
        c = m.CustomCode(name=name, code_type=ctype, description=desc, owner="custom-code-team")
        db.add(c)
        ccs[name] = c
    db.flush()

    # ------------------------------------------------------------ config items
    cfg_defs = [
        ("PRICING_COND_TYPE_ZPR0", "PRICING", "ZPR0|STD|2026", True),
        ("PRICING_PROCEDURE_STD", "PRICING", "VAA00001", False),
        ("PRICING_COPY_CONTROL_BILLING", "PRICING", "ORDER->BILLING COPY RULES", True),
        ("OUTPUT_DET_BILLING_INVOIC", "OUTPUT", "RD04|EDI-INVOIC", False),
        ("PO_DOC_TYPE_NB", "DOCUMENT_TYPE", "NB-STANDARD-PO", False),
        ("PO_RELEASE_STRATEGY", "RELEASE_STRATEGY", "T2|>50K EUR 2 EYES", False),
        ("POSTING_KEYS_GL_40_50", "POSTING_KEY", "40 DEBIT / 50 CREDIT", False),
        ("DOC_TYPE_SA_GL", "DOCUMENT_TYPE", "SA-GL MANUAL", False),
        ("FX_VALUATION_METHOD", "VALUATION", "SAMBA-LOWEST", True),
        ("PAYROLL_PERIOD_SCHEMA", "PAYROLL", "MONTHLY-X000", False),
        ("DUNNING_LEVELS", "OUTPUT", "4 LEVELS", False),
        ("STOCK_POSTING_RULES", "IM_MANAGEMENT", "COUNT->UNRESTRICTED", False),
    ]
    cfgs = {}
    for key, cat, val, vflow in cfg_defs:
        c = m.ConfigItem(key=key, category=cat, value=val, value_flow=vflow,
                         description=f"Simulated customizing record {key}")
        db.add(c)
        cfgs[key] = c
    db.flush()

    # ---------------------------------------------------------------- tables
    tbl_defs = [
        ("sales_orders", "SD", False, "Sales document header"),
        ("sales_order_items", "SD", True, "Sales document items with pricing results"),
        ("deliveries", "SD", False, "Outbound deliveries"),
        ("billing_docs", "SD", True, "Billing documents (net/tax amounts)"),
        ("accounting_docs", "FI", True, "Accounting documents"),
        ("purchase_orders", "MM", True, "Purchase order headers incl. release status"),
        ("purchase_order_items", "MM", True, "Purchase order items"),
        ("material_docs", "MM", True, "Material documents (goods movements)"),
        ("material_stock", "MM", True, "Current stock by material/plant"),
        ("gl_entries", "FI", True, "General ledger line items"),
        ("cost_centers", "CO", False, "Cost center master"),
        ("payroll_results", "HR", True, "Payroll results per employee/period"),
    ]
    tbls = {}
    for name, mod, vflow, desc in tbl_defs:
        t = m.SapTable(name=name, module=mod, value_flow=vflow, description=desc)
        db.add(t)
        tbls[name] = t
    db.flush()

    fields = [
        ("sales_orders", ["order_id", "customer_id", "net_value", "pricing_date", "sales_org"]),
        ("sales_order_items", ["order_id", "item_no", "material_id", "qty", "unit_price", "condition_type"]),
        ("deliveries", ["delivery_id", "order_id", "ship_date", "qty"]),
        ("billing_docs", ["billing_id", "order_id", "net_amount", "tax_amount", "currency"]),
        ("accounting_docs", ["doc_id", "billing_id", "amount", "clearing_status", "gl_account"]),
        ("purchase_orders", ["po_id", "vendor_id", "po_value", "release_status"]),
        ("purchase_order_items", ["po_id", "item_no", "material_id", "qty", "net_price"]),
        ("material_docs", ["mat_doc_id", "po_id", "movement_type", "qty"]),
        ("material_stock", ["material_id", "plant", "qty", "stock_value"]),
        ("gl_entries", ["entry_id", "doc_id", "account", "amount", "currency", "fx_rate"]),
        ("cost_centers", ["cost_center", "valid_from", "manager"]),
        ("payroll_results", ["employee_id", "period", "gross", "net_pay", "tax"]),
    ]
    flds = {}
    for tname, fnames in fields:
        for fname in fnames:
            f = m.TableField(table_id=tbls[tname].id, name=fname)
            db.add(f)
            flds[(tname, fname)] = f
    db.flush()

    # ------------------------------------------------------------- interfaces
    ifaces = {}
    iface_defs = [
        ("ORDERS_OUT", "OUTBOUND", "IDOC_LIKE", "VENDOR_PORTAL", "Purchase order transmission"),
        ("INVOIC_OUT", "OUTBOUND", "IDOC_LIKE", "CUSTOMER_EDI", "Customer invoice EDI feed"),
        ("PAYMENT_IN", "INBOUND", "IDOC_LIKE", "BANK_GATEWAY", "Inbound bank payment statements"),
        ("API_SALES_ORDER_SRV", "INBOUND", "ODATA_LIKE", "EXTERNAL_SHOP", "OData-like sales order creation API"),
        ("API_PURCHASEORDER_SRV", "INBOUND", "ODATA_LIKE", "SRM_SYSTEM", "OData-like purchase order API"),
    ]
    for name, direction, kind, partner, desc in iface_defs:
        i = m.InterfaceDef(name=name, direction=direction, kind=kind, partner=partner, description=desc)
        db.add(i)
        ifaces[name] = i
    db.flush()

    # ------------------------------------------------------------- batch jobs
    jobs = {}
    job_defs = [
        ("NIGHTLY_STOCK_SYNC", "NIGHTLY 02:00", "Syncs material stock from daily movements"),
        ("FX_REVALUATION_NIGHTLY", "NIGHTLY 03:00", "Runs foreign currency valuation batch"),
        ("DUNNING_NIGHTLY", "WEEKLY FRI 22:00", "Customer dunning proposal run"),
        ("FI_RECON_NIGHTLY", "NIGHTLY 04:00", "Finance reconciliation batch run"),
    ]
    for name, sched, desc in job_defs:
        j = m.BatchJob(name=name, schedule=sched, description=desc)
        db.add(j)
        jobs[name] = j
    db.flush()

    # ------------------------------------------------------------------ roles
    roles = {}
    role_defs = [
        ("ROLE_SD_SALES_REP", "P_SD_SALES_T1", "Order entry clerks"),
        ("ROLE_SD_BILLING_CLERK", "P_SD_BILL_T1", "Billing specialists"),
        ("ROLE_MM_BUYER", "P_MM_BUYER_T2", "Buyers with PO release authority"),
        ("ROLE_FI_ACCOUNTANT", "P_FI_ACC_T1", "Financial accountants"),
        ("ROLE_HR_PAYROLL_ADMIN", "P_HR_PAY_ADMIN", "Payroll administrators"),
        ("ROLE_PAYROLL_CLERK", "P_HR_PAY_DISP", "Read-only payroll display clerks"),
        ("ROLE_IM_WAREHOUSE_CLERK", "P_IM_WH_T1", "Warehouse inventory clerks"),
    ]
    for name, profile, desc in role_defs:
        r = m.Role(name=name, profile=profile, description=desc)
        db.add(r)
        roles[name] = r
    db.flush()

    # -------------------------------------------------------------- test cases
    tc_defs = [
        # code, name, process, criticality, kind, runs, failures
        ("SO_CREATE_TEST", "Create sales order happy path incl. pricing", p_o2c, "CRITICAL", "FUNCTIONAL", 240, 14),
        ("SO_DELIVER_TEST", "Create outbound delivery from order", p_o2c, "HIGH", "FUNCTIONAL", 220, 9),
        ("BILLING_CREATE_TEST", "Create billing doc; assert net amount golden copy", p_o2c, "CRITICAL", "FUNCTIONAL", 210, 21),
        ("INVOIC_PAYLOAD_TEST", "Validate INVOIC_OUT payload vs billing document", p_o2c, "HIGH", "INTERFACE", 180, 12),
        ("SO_API_CONTRACT_TEST", "API_SALES_ORDER_SRV contract test", p_o2c, "HIGH", "API", 90, 4),
        ("PO_CREATE_TEST", "Create standard purchase order", p_p2p, "HIGH", "FUNCTIONAL", 200, 8),
        ("PO_APPROVE_TEST", "Release PO through strategy levels", p_p2p, "HIGH", "FUNCTIONAL", 190, 11),
        ("PO_RECEIVE_TEST", "Post goods receipt for PO", p_p2p, "MEDIUM", "FUNCTIONAL", 185, 5),
        ("PO_INVOICE_TEST", "Enter vendor invoice and verify postings", p_p2p, "HIGH", "FUNCTIONAL", 175, 9),
        ("ORDERS_PAYLOAD_TEST", "Validate ORDERS_OUT payload to vendor portal", p_p2p, "HIGH", "INTERFACE", 150, 7),
        ("API_PO_CONTRACT_TEST", "API_PURCHASEORDER_SRV contract test", p_p2p, "MEDIUM", "API", 60, 2),
        ("GL_POST_TEST", "Manual GL posting debit/credit balance", p_r2r, "CRITICAL", "FUNCTIONAL", 300, 6),
        ("FI_RECONCILIATION_TEST", "Finance reconciliation zero-difference run", p_r2r, "CRITICAL", "RECONCILIATION", 280, 17),
        ("FX_REVALUATION_TEST", "FX valuation of open items vs golden rates", p_r2r, "HIGH", "FUNCTIONAL", 120, 6),
        ("PAYROLL_DRYRUN_TEST", "Payroll simulation dry-run variance check", p_htr, "CRITICAL", "FUNCTIONAL", 130, 4),
        ("STOCK_SYNC_TEST", "Nightly stock sync consistency check", p_im, "MEDIUM", "FUNCTIONAL", 200, 3),
        ("STOCK_COUNT_TEST", "Physical count posting updates stock", p_im, "LOW", "FUNCTIONAL", 160, 2),
    ]
    tcs = {}
    for code, name, proc, crit, kind, runs, fails in tc_defs:
        t = m.TestCase(code=code, name=name, process_id=proc.id, criticality=crit,
                       kind=kind, historical_runs=runs, historical_failures=fails,
                       last_status="PASS", avg_duration_s=8.0 + runs % 17)
        db.add(t)
        tcs[code] = t
    db.flush()

    # ------------------------------------------------------- defect seeds (validation simulation)
    db.add_all([
        m.DefectSeed(scenario_tag="PRICING_CANONICAL", test_code="BILLING_CREATE_TEST",
                     failure_reason="Billing net_amount deviates from golden copy by pricing delta "
                                    "(expected 11800.00 EUR, got 10620.00 EUR) - condition ZPR0 applied twice.",
                     severity="CRITICAL"),
        m.DefectSeed(scenario_tag="PRICING_CANONICAL", test_code="INVOIC_PAYLOAD_TEST",
                     failure_reason="INVOIC_OUT segment E1EDK01 amount mismatch versus billing document.",
                     severity="HIGH"),
    ])

    # ---------------------------------------------------------------- graph edges
    E = []

    def edge(etype, src, dst):
        E.append(m.GraphEdgeRow(edge_type=etype, src_type=src[0], src_id=src[1],
                                dst_type=dst[0], dst_id=dst[1]))

    P = lambda o: ("PROCESS", o.id)
    S = lambda o: ("STEP", o.id)
    T = lambda o: ("TRANSACTION", o.id)
    F = lambda o: ("FIORI_APP", o.id)
    C = lambda o: ("CUSTOM_CODE", o.id)
    K = lambda o: ("CONFIG_ITEM", o.id)
    TB = lambda o: ("TABLE", o.id)
    FL = lambda o: ("TABLE_FIELD", o.id)
    I = lambda o: ("INTERFACE", o.id)
    J = lambda o: ("BATCH_JOB", o.id)
    R = lambda o: ("ROLE", o.id)
    TC = lambda o: ("TEST_CASE", o.id)

    # process -> steps
    edge("PROCESS_USES_STEP", P(p_o2c), S(steps["SO_ENTRY"]))
    edge("PROCESS_USES_STEP", P(p_o2c), S(steps["DELIVERY"]))
    edge("PROCESS_USES_STEP", P(p_o2c), S(steps["BILLING"]))
    edge("PROCESS_USES_STEP", P(p_o2c), S(steps["ACC_RELEASE"]))
    edge("PROCESS_USES_STEP", P(p_p2p), S(steps["PO_CREATE"]))
    edge("PROCESS_USES_STEP", P(p_p2p), S(steps["PO_APPROVE"]))
    edge("PROCESS_USES_STEP", P(p_p2p), S(steps["PO_RECEIVE"]))
    edge("PROCESS_USES_STEP", P(p_p2p), S(steps["PO_INVOICE"]))
    edge("PROCESS_USES_STEP", P(p_r2r), S(steps["GL_POST"]))
    edge("PROCESS_USES_STEP", P(p_r2r), S(steps["FX_RUN"]))
    edge("PROCESS_USES_STEP", P(p_r2r), S(steps["FI_RECON"]))
    edge("PROCESS_USES_STEP", P(p_htr), S(steps["PAYROLL_SIM"]))
    edge("PROCESS_USES_STEP", P(p_im), S(steps["STOCK_COUNT"]))
    edge("PROCESS_USES_STEP", P(p_im), S(steps["STOCK_VIEW"]))

    # steps -> transactions
    edge("STEP_RUNS_TRANSACTION", S(steps["SO_ENTRY"]), T(txs["SO_CREATE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["DELIVERY"]), T(txs["SO_DELIVER"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["BILLING"]), T(txs["BILLING_CREATE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["ACC_RELEASE"]), T(txs["GL_POST"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["PO_CREATE"]), T(txs["PO_CREATE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["PO_APPROVE"]), T(txs["PO_RELEASE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["PO_RECEIVE"]), T(txs["PO_RECEIVE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["PO_INVOICE"]), T(txs["PO_INVOICE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["GL_POST"]), T(txs["GL_POST"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["FX_RUN"]), T(txs["FX_REVALUATE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["FI_RECON"]), T(txs["FI_RECONCILE_RUN"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["PAYROLL_SIM"]), T(txs["PAYROLL_SIMULATE"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["STOCK_COUNT"]), T(txs["STOCK_COUNT_ENTRY"]))
    edge("STEP_RUNS_TRANSACTION", S(steps["STOCK_VIEW"]), T(txs["STOCK_OVERVIEW"]))

    # transactions <-> tables
    edge("TRANSACTION_WRITES_TABLE", T(txs["SO_CREATE"]), TB(tbls["sales_orders"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["SO_CREATE"]), TB(tbls["sales_order_items"]))
    edge("TRANSACTION_READS_TABLE", T(txs["SO_DELIVER"]), TB(tbls["sales_orders"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["SO_DELIVER"]), TB(tbls["deliveries"]))
    edge("TRANSACTION_READS_TABLE", T(txs["BILLING_CREATE"]), TB(tbls["sales_orders"]))
    edge("TRANSACTION_READS_TABLE", T(txs["BILLING_CREATE"]), TB(tbls["sales_order_items"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["BILLING_CREATE"]), TB(tbls["billing_docs"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["BILLING_CREATE"]), TB(tbls["accounting_docs"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["GL_POST"]), TB(tbls["accounting_docs"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["GL_POST"]), TB(tbls["gl_entries"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["PO_CREATE"]), TB(tbls["purchase_orders"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["PO_CREATE"]), TB(tbls["purchase_order_items"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["PO_RELEASE"]), TB(tbls["purchase_orders"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["PO_RECEIVE"]), TB(tbls["material_docs"]))
    edge("TRANSACTION_READS_TABLE", T(txs["PO_INVOICE"]), TB(tbls["purchase_order_items"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["PO_INVOICE"]), TB(tbls["accounting_docs"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["FX_REVALUATE"]), TB(tbls["gl_entries"]))
    edge("TRANSACTION_READS_TABLE", T(txs["FX_REVALUATE"]), TB(tbls["cost_centers"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["PAYROLL_SIMULATE"]), TB(tbls["payroll_results"]))
    edge("TRANSACTION_WRITES_TABLE", T(txs["STOCK_COUNT_ENTRY"]), TB(tbls["material_stock"]))
    edge("TRANSACTION_READS_TABLE", T(txs["STOCK_OVERVIEW"]), TB(tbls["material_stock"]))

    # table fields -> custom code
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("sales_order_items", "unit_price")]), C(ccs["Z_PRICING_DETERMINATION_EXIT"]))
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("sales_order_items", "condition_type")]), C(ccs["Z_PRICING_DETERMINATION_EXIT"]))
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("sales_orders", "sales_org")]), C(ccs["Z_ORDER_VALIDATION_BADI"]))
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("payroll_results", "net_pay")]), C(ccs["Z_PAYROLL_SCHEMA_EXIT"]))

    # custom code called by transactions
    edge("CUSTOM_CODE_CALLED_BY_TRANSACTION", C(ccs["Z_PRICING_DETERMINATION_EXIT"]), T(txs["SO_CREATE"]))
    edge("CUSTOM_CODE_CALLED_BY_TRANSACTION", C(ccs["Z_PRICING_DETERMINATION_EXIT"]), T(txs["BILLING_CREATE"]))
    edge("CUSTOM_CODE_CALLED_BY_TRANSACTION", C(ccs["Z_ORDER_VALIDATION_BADI"]), T(txs["SO_CREATE"]))
    edge("CUSTOM_CODE_CALLED_BY_TRANSACTION", C(ccs["Z_PO_RELEASE_WORKFLOW"]), T(txs["PO_RELEASE"]))
    edge("CUSTOM_CODE_CALLED_BY_TRANSACTION", C(ccs["Z_PAYROLL_SCHEMA_EXIT"]), T(txs["PAYROLL_SIMULATE"]))

    # custom code reads/writes tables
    edge("CUSTOM_CODE_WRITES_TABLE", C(ccs["Z_MM_STOCK_SYNC_REPORT"]), TB(tbls["material_stock"]))
    edge("CUSTOM_CODE_READS_TABLE", C(ccs["Z_MM_STOCK_SYNC_REPORT"]), TB(tbls["purchase_order_items"]))
    edge("CUSTOM_CODE_READS_TABLE", C(ccs["Z_FI_RECONCILIATION_JOB"]), TB(tbls["accounting_docs"]))
    edge("CUSTOM_CODE_READS_TABLE", C(ccs["Z_FI_RECONCILIATION_JOB"]), TB(tbls["gl_entries"]))
    edge("CUSTOM_CODE_WRITES_TABLE", C(ccs["Z_FX_REVALUATION_REPORT"]), TB(tbls["gl_entries"]))
    edge("CUSTOM_CODE_WRITES_TABLE", C(ccs["Z_PO_RELEASE_WORKFLOW"]), TB(tbls["purchase_orders"]))
    edge("CUSTOM_CODE_READS_TABLE", C(ccs["Z_PO_OUTPUT_PROGRAM"]), TB(tbls["purchase_orders"]))
    edge("CUSTOM_CODE_READS_TABLE", C(ccs["Z_INVOIC_OUTPUT_PROGRAM"]), TB(tbls["billing_docs"]))
    edge("CUSTOM_CODE_WRITES_TABLE", C(ccs["Z_PAYMENT_MATCHING_INBOUND"]), TB(tbls["accounting_docs"]))
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("accounting_docs", "clearing_status")]), C(ccs["Z_PAYMENT_MATCHING_INBOUND"]))
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("billing_docs", "net_amount")]), C(ccs["Z_INVOIC_OUTPUT_PROGRAM"]))
    edge("TABLE_FIELD_USED_BY_CUSTOM_CODE", FL(flds[("purchase_orders", "po_value")]), C(ccs["Z_PO_RELEASE_WORKFLOW"]))

    # interfaces
    edge("INTERFACE_IMPL_BY_CUSTOM_CODE", I(ifaces["ORDERS_OUT"]), C(ccs["Z_PO_OUTPUT_PROGRAM"]))
    edge("INTERFACE_IMPL_BY_CUSTOM_CODE", I(ifaces["INVOIC_OUT"]), C(ccs["Z_INVOIC_OUTPUT_PROGRAM"]))
    edge("INTERFACE_IMPL_BY_CUSTOM_CODE", I(ifaces["PAYMENT_IN"]), C(ccs["Z_PAYMENT_MATCHING_INBOUND"]))
    edge("PROCESS_CALLS_INTERFACE", P(p_o2c), I(ifaces["INVOIC_OUT"]))
    edge("PROCESS_CALLS_INTERFACE", P(p_o2c), I(ifaces["API_SALES_ORDER_SRV"]))
    edge("PROCESS_CALLS_INTERFACE", P(p_p2p), I(ifaces["ORDERS_OUT"]))
    edge("PROCESS_CALLS_INTERFACE", P(p_p2p), I(ifaces["API_PURCHASEORDER_SRV"]))
    edge("PROCESS_CALLS_INTERFACE", P(p_r2r), I(ifaces["PAYMENT_IN"]))
    edge("TRANSACTION_CALLS_INTERFACE", T(txs["SO_CREATE"]), I(ifaces["API_SALES_ORDER_SRV"]))
    edge("TRANSACTION_CALLS_INTERFACE", T(txs["PO_CREATE"]), I(ifaces["API_PURCHASEORDER_SRV"]))

    # config usage
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PRICING_COND_TYPE_ZPR0"]), T(txs["SO_CREATE"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PRICING_COND_TYPE_ZPR0"]), T(txs["BILLING_CREATE"]))
    edge("CONFIG_USED_BY_CUSTOM_CODE", K(cfgs["PRICING_COND_TYPE_ZPR0"]), C(ccs["Z_PRICING_DETERMINATION_EXIT"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PRICING_PROCEDURE_STD"]), T(txs["SO_CREATE"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PRICING_COPY_CONTROL_BILLING"]), T(txs["BILLING_CREATE"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["OUTPUT_DET_BILLING_INVOIC"]), T(txs["BILLING_CREATE"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PO_DOC_TYPE_NB"]), T(txs["PO_CREATE"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PO_RELEASE_STRATEGY"]), T(txs["PO_RELEASE"]))
    edge("CONFIG_USED_BY_CUSTOM_CODE", K(cfgs["PO_RELEASE_STRATEGY"]), C(ccs["Z_PO_RELEASE_WORKFLOW"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["POSTING_KEYS_GL_40_50"]), T(txs["GL_POST"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["DOC_TYPE_SA_GL"]), T(txs["GL_POST"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["FX_VALUATION_METHOD"]), T(txs["FX_REVALUATE"]))
    edge("CONFIG_USED_BY_CUSTOM_CODE", K(cfgs["FX_VALUATION_METHOD"]), C(ccs["Z_FX_REVALUATION_REPORT"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["PAYROLL_PERIOD_SCHEMA"]), T(txs["PAYROLL_SIMULATE"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["DUNNING_LEVELS"]), T(txs["DUNNING_RUN"]))
    edge("CONFIG_USED_BY_TRANSACTION", K(cfgs["STOCK_POSTING_RULES"]), T(txs["STOCK_COUNT_ENTRY"]))

    # tests validate objects
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["SO_CREATE"]), TC(tcs["SO_CREATE_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["SO_DELIVER"]), TC(tcs["SO_DELIVER_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["BILLING_CREATE"]), TC(tcs["BILLING_CREATE_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", I(ifaces["INVOIC_OUT"]), TC(tcs["INVOIC_PAYLOAD_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", I(ifaces["API_SALES_ORDER_SRV"]), TC(tcs["SO_API_CONTRACT_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["PO_CREATE"]), TC(tcs["PO_CREATE_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["PO_RELEASE"]), TC(tcs["PO_APPROVE_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["PO_RECEIVE"]), TC(tcs["PO_RECEIVE_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["PO_INVOICE"]), TC(tcs["PO_INVOICE_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", I(ifaces["ORDERS_OUT"]), TC(tcs["ORDERS_PAYLOAD_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", I(ifaces["API_PURCHASEORDER_SRV"]), TC(tcs["API_PO_CONTRACT_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["GL_POST"]), TC(tcs["GL_POST_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", C(ccs["Z_FI_RECONCILIATION_JOB"]), TC(tcs["FI_RECONCILIATION_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", C(ccs["Z_FX_REVALUATION_REPORT"]), TC(tcs["FX_REVALUATION_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["PAYROLL_SIMULATE"]), TC(tcs["PAYROLL_DRYRUN_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", C(ccs["Z_MM_STOCK_SYNC_REPORT"]), TC(tcs["STOCK_SYNC_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", T(txs["STOCK_COUNT_ENTRY"]), TC(tcs["STOCK_COUNT_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", P(p_r2r), TC(tcs["FI_RECONCILIATION_TEST"]))
    edge("OBJECT_VALIDATED_BY_TEST", P(p_htr), TC(tcs["PAYROLL_DRYRUN_TEST"]))

    # roles assigned to processes
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_SD_SALES_REP"]), P(p_o2c))
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_SD_BILLING_CLERK"]), P(p_o2c))
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_MM_BUYER"]), P(p_p2p))
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_FI_ACCOUNTANT"]), P(p_r2r))
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_HR_PAYROLL_ADMIN"]), P(p_htr))
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_PAYROLL_CLERK"]), P(p_htr))
    edge("USER_ROLE_ASSIGNED_TO_PROCESS", R(roles["ROLE_IM_WAREHOUSE_CLERK"]), P(p_im))

    # fiori tiles launch transactions
    edge("FIORI_APP_LAUNCHES_TRANSACTION", F(fios["FIORI_ORDER_TRACK"]), T(txs["SO_CREATE"]))
    edge("FIORI_APP_LAUNCHES_TRANSACTION", F(fios["FIORI_BILLING"]), T(txs["BILLING_CREATE"]))
    edge("FIORI_APP_LAUNCHES_TRANSACTION", F(fios["FIORI_MY_PO"]), T(txs["PO_RELEASE"]))
    edge("FIORI_APP_LAUNCHES_TRANSACTION", F(fios["FIORI_GL_DASHBOARD"]), T(txs["GL_POST"]))
    edge("FIORI_APP_LAUNCHES_TRANSACTION", F(fios["FIORI_STOCK_OVERVIEW"]), T(txs["STOCK_OVERVIEW"]))
    edge("FIORI_APP_LAUNCHES_TRANSACTION", F(fios["FIORI_PAYROLL_SIM"]), T(txs["PAYROLL_SIMULATE"]))

    # batch jobs
    edge("BATCH_JOB_RUNS_CUSTOM_CODE", J(jobs["NIGHTLY_STOCK_SYNC"]), C(ccs["Z_MM_STOCK_SYNC_REPORT"]))
    edge("BATCH_JOB_SUPPORTS_PROCESS", J(jobs["NIGHTLY_STOCK_SYNC"]), P(p_im))
    edge("BATCH_JOB_RUNS_CUSTOM_CODE", J(jobs["FX_REVALUATION_NIGHTLY"]), C(ccs["Z_FX_REVALUATION_REPORT"]))
    edge("BATCH_JOB_SUPPORTS_PROCESS", J(jobs["FX_REVALUATION_NIGHTLY"]), P(p_r2r))
    # DUNNING_NIGHTLY drives the standard dunning proposal run (scenery node,
    # intentionally without further wiring).
    edge("BATCH_JOB_RUNS_CUSTOM_CODE", J(jobs["FI_RECON_NIGHTLY"]), C(ccs["Z_FI_RECONCILIATION_JOB"]))
    edge("BATCH_JOB_SUPPORTS_PROCESS", J(jobs["FI_RECON_NIGHTLY"]), P(p_r2r))

    db.add_all(E)

    # ------------------------------------------------------- sample queue transports
    sample = m.Transport(
        transport_id="SIMK900100", title="Baseline customizing refresh", kind="CUSTOMIZING",
        change_type="CONFIG_CHANGE", status="APPROVED", size_bucket="SMALL",
        objects_changed=1, config_changes=1, loc_delta=0, scenario_tag="",
    )
    db.add(sample)
    db.flush()
    db.add(m.TransportObject(
        transport_fk=sample.id,
        object_type="CONFIG_ITEM", object_key="DUNNING_LEVELS", change_action="MODIFY",
        value_affecting=False, details={"note": "cosmetic dunning text"},
    ))
    db.add(m.EventRow(kind="SEED", ref_type="SIMULATOR", ref_id=0,
                      message="Simulated SAP-like landscape seeded"))

    db.commit()
    counts = {
        "processes": db.query(m.Process).count(),
        "process_steps": db.query(m.ProcessStep).count(),
        "transactions": db.query(m.Transaction).count(),
        "fiori_apps": db.query(m.FioriApp).count(),
        "custom_code": db.query(m.CustomCode).count(),
        "config_items": db.query(m.ConfigItem).count(),
        "tables": db.query(m.SapTable).count(),
        "table_fields": db.query(m.TableField).count(),
        "interfaces": db.query(m.InterfaceDef).count(),
        "batch_jobs": db.query(m.BatchJob).count(),
        "roles": db.query(m.Role).count(),
        "test_cases": db.query(m.TestCase).count(),
        "graph_edges": db.query(m.GraphEdgeRow).count(),
        "defect_seeds": db.query(m.DefectSeed).count(),
        "transports": db.query(m.Transport).count(),
    }
    return counts


if __name__ == "__main__":
    from backend.app.db import get_session_factory, init_db

    init_db()
    session = get_session_factory()()
    counts = seed_landscape(session)
    print(SIMULATION_LABEL)
    print("Seeded:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
