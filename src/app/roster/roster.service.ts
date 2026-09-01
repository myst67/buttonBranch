import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  GeneratedRoster,
  GenerateOptions,
  HistoryMonth,
  TrainingReport,
  UploadResult,
} from './roster.models';

/** Thin wrapper over the roster API. `/api` is proxied to the backend in dev. */
@Injectable({ providedIn: 'root' })
export class RosterService {
  private readonly http = inject(HttpClient);
  private readonly base = '/api';

  /** Upload last month's sheet - this is also what retrains the model. */
  upload(file: File, month?: string): Promise<UploadResult> {
    const form = new FormData();
    form.append('file', file, file.name);
    if (month) {
      form.append('month', month);
    }
    return firstValueFrom(this.http.post<UploadResult>(`${this.base}/history/upload`, form));
  }

  history(): Promise<{ months: HistoryMonth[]; model: TrainingReport }> {
    return firstValueFrom(
      this.http.get<{ months: HistoryMonth[]; model: TrainingReport }>(`${this.base}/history`),
    );
  }

  deleteMonth(month: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`${this.base}/history/${month}`));
  }

  train(): Promise<TrainingReport> {
    return firstValueFrom(this.http.post<TrainingReport>(`${this.base}/train`, {}));
  }

  generate(options: GenerateOptions): Promise<GeneratedRoster> {
    return firstValueFrom(
      this.http.post<GeneratedRoster>(`${this.base}/roster/generate`, options),
    );
  }

  exportUrl(rosterId: string, format: 'xlsx' | 'csv'): string {
    return `${this.base}/roster/${rosterId}/export.${format}`;
  }
}
