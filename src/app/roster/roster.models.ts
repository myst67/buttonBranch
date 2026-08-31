/** Shapes returned by the FastAPI backend (see backend/app/main.py). */

export interface ModelMetrics {
  trained: boolean;
  estimator: string;
  n_samples: number;
  n_months: number;
  top1_accuracy: number | null;
  roc_auc: number | null;
  evaluation: string;
  blend_weight: number;
  top_features: Array<[string, number]>;
}

export interface TrainingReport {
  n_history_months: number;
  months: string[];
  shift_model: ModelMetrics;
  off_model: ModelMetrics;
  trained_at?: string;
  version?: string;
}

export interface ParsedEmployee {
  name: string;
  clients: string[];
  shift: string;
  off_start: number | null;
  off_length: number | null;
}

export interface UploadResult {
  month: string;
  month_label: string;
  target_month: string;
  employees: ParsedEmployee[];
  clients: string[];
  warnings: string[];
  blockers: string[];
  ready: boolean;
  training: TrainingReport;
}

export interface HistoryMonth {
  month: string;
  month_label: string;
  employees: number;
  clients: number;
  with_off_pattern: number;
  warnings: number;
}

export interface RosterRow {
  name: string;
  clients: string[];
  client_label: string;
  shift: string;
  previous_shift: string | null;
  off_start: number;
  off_length: number;
  cells: string[];
  reason: string;
  shift_score: number;
  off_score: number;
  working_days: number;
  off_days: number;
}

export interface CoverageRow {
  client: string;
  shift: string;
  headcount: number;
  per_day: number[];
  min: number;
}

export interface RosterDay {
  label: string;
  weekday: number;
  date: string;
}

export interface GeneratedRoster {
  month: string;
  month_label: string;
  header: string[];
  days: RosterDay[];
  rows: RosterRow[];
  coverage: CoverageRow[];
  clients: string[];
  meta: {
    id: string;
    generated_at: string;
    source_month: string | null;
    solver_status: string;
    solve_seconds: number;
    objective: number;
    balance_slack_used: number;
    notes: string[];
    training: TrainingReport;
  };
  validation: {
    ok: boolean;
    errors: string[];
    checked: { employees: number; clients: number; days: number; client_shift_day_slots: number };
  };
}

export interface GenerateOptions {
  month?: string;
  source_month?: string;
  seed?: number;
  time_limit_seconds?: number;
  min_per_client_shift?: number;
  balance_slack?: number;
}
