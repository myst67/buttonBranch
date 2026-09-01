import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ModelPanel } from './roster/model-panel';
import { GeneratedRoster, HistoryMonth, TrainingReport, UploadResult } from './roster/roster.models';
import { RosterService } from './roster/roster.service';
import { RosterTable } from './roster/roster-table';
import { UploadPanel } from './roster/upload-panel';

@Component({
  selector: 'app-root',
  imports: [FormsModule, UploadPanel, ModelPanel, RosterTable],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  private readonly service = inject(RosterService);

  protected readonly uploadResult = signal<UploadResult | undefined>(undefined);
  protected readonly history = signal<HistoryMonth[]>([]);
  protected readonly training = signal<TrainingReport | undefined>(undefined);
  protected readonly roster = signal<GeneratedRoster | undefined>(undefined);

  protected readonly uploading = signal(false);
  protected readonly generating = signal(false);
  protected readonly uploadError = signal<string | undefined>(undefined);
  protected readonly generateError = signal<string | undefined>(undefined);
  protected readonly generateReasons = signal<string[]>([]);

  protected options = {
    month: '',
    seed: 42,
    time_limit_seconds: 20,
    min_per_client_shift: 2,
    balance_slack: 1,
  };

  protected readonly canGenerate = computed(
    () => !this.generating() && (this.history().length > 0 || !!this.uploadResult()));

  ngOnInit(): void {
    void this.refreshHistory();
  }

  protected async refreshHistory(): Promise<void> {
    try {
      const response = await this.service.history();
      this.history.set(response.months);
      this.training.set(response.model);
      if (!this.options.month && response.months.length) {
        this.options.month = this.nextMonth(response.months[response.months.length - 1].month);
      }
    } catch {
      // The banner on the first failed action says it better than a startup error.
    }
  }

  protected async onUpload(event: { file: File; month?: string }): Promise<void> {
    this.uploading.set(true);
    this.uploadError.set(undefined);
    try {
      const result = await this.service.upload(event.file, event.month);
      this.uploadResult.set(result);
      this.training.set(result.training);
      this.options.month = result.target_month;
      await this.refreshHistory();
    } catch (error) {
      this.uploadError.set(this.describe(error as HttpErrorResponse));
    } finally {
      this.uploading.set(false);
    }
  }

  protected async onRemoveMonth(month: string): Promise<void> {
    await this.service.deleteMonth(month);
    await this.refreshHistory();
  }

  protected async generate(): Promise<void> {
    this.generating.set(true);
    this.generateError.set(undefined);
    this.generateReasons.set([]);
    try {
      const roster = await this.service.generate(this.options);
      this.roster.set(roster);
      this.training.set(roster.meta.training);
    } catch (error) {
      const response = error as HttpErrorResponse;
      const detail = response.error?.detail;
      if (detail?.reasons) {
        this.generateError.set('The rules cannot all be met for this team:');
        this.generateReasons.set(detail.reasons);
      } else {
        this.generateError.set(this.describe(response));
      }
    } finally {
      this.generating.set(false);
    }
  }

  private nextMonth(month: string): string {
    const [year, number] = month.split('-').map(Number);
    return number === 12 ? `${year + 1}-01` : `${year}-${String(number + 1).padStart(2, '0')}`;
  }

  private describe(error: HttpErrorResponse): string {
    if (error.status === 0) {
      return 'The backend is not reachable. Start it with: uvicorn app.main:app --port 8000';
    }
    const detail = error.error?.detail;
    return typeof detail === 'string' ? detail : `Request failed (${error.status}).`;
  }
}
