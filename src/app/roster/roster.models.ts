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

export interface GapMove {
  employee: string;
  client: string;
  clients_before: number;
  clients_after: number;
  previous_shift: string | null;
  why: string;
}

export interface ShortClient {
  client: string;
  employees: number;
  needed: number;
  short: number;
  shifts_blocked: { shift: string; eligible: number; needed: number; note: string }[];
}

/** What the team cannot cover, and the smallest reassignment that would fix it. */
export interface GapReport {
  ok: boolean;
  needed_per_client: number;
  min_per_client_shift: number;
  clients_short: ShortClient[];
  moves: GapMove[];
  unresolved: string[];
  summary: string;
}

export interface UploadResult {
  month: string;
  month_label: string;
  target_month: string;
  employees: ParsedEmployee[];
  clients: string[];
  warnings: string[];
  /** Arithmetic problems: no roster obeying rule 5 exists while these hold. */
  blockers: string[];
  /** Rule 2 problems about the team's shape. A roster is still possible. */
  advisories: string[];
  ready: boolean;
  clean: boolean;
  gaps: GapReport;
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
    /** What the team could not cover, and the reassignment that would fix it. */
    gaps: GapReport;
  };
  validation: {
    ok: boolean;
    /** Rules 3-5 on the produced schedule, independent of the team's shape. */
    schedule_ok: boolean;
    errors: string[];
    /** Rule 2 findings about the team that was fed in. */
    team_shape: string[];
    /** True when nothing was left uncovered, whether or not gaps were allowed. */
    fully_covered: boolean;
    /** Client/shift/day slots left unstaffed, when gaps were permitted. */
    coverage_gaps: string[];
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
  /** Build even though the team breaks rule 2. Scheduling rules stay hard. */
  accept_team_shape?: boolean;
  /** Build the best roster this team allows, leaving the rest as reported gaps. */
  allow_coverage_gaps?: boolean;
}
