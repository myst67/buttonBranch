import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import {
  GeneratedRoster, GenerateOptions, HistoryMonth, TrainingReport, UploadResult
} from './roster.models';

/** Thin wrapper over the roster API. `/api` is proxied to the backend in dev. */
@Injectable({ providedIn: 'root' })
export class RosterService {
  private readonly base = '/api';

  constructor(private http: HttpClient) {}

  /** Upload last month's sheet - this is also what retrains the model. */
  upload(file: File, month?: string): Observable<UploadResult> {
    const form = new FormData();
    form.append('file', file, file.name);
    if (month) {
      form.append('month', month);
    }
    return this.http.post<UploadResult>(`${this.base}/history/upload`, form);
  }

  history(): Observable<{ months: HistoryMonth[]; model: TrainingReport }> {
    return this.http.get<{ months: HistoryMonth[]; model: TrainingReport }>(`${this.base}/history`);
  }

  deleteMonth(month: string): Observable<any> {
    return this.http.delete(`${this.base}/history/${month}`);
  }

  train(): Observable<TrainingReport> {
    return this.http.post<TrainingReport>(`${this.base}/train`, {});
  }

  generate(options: GenerateOptions): Observable<GeneratedRoster> {
    return this.http.post<GeneratedRoster>(`${this.base}/roster/generate`, options);
  }

  exportUrl(rosterId: string, format: 'xlsx' | 'csv'): string {
    return `${this.base}/roster/${rosterId}/export.${format}`;
  }
}
