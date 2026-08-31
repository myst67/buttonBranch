import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';

import { GeneratedRoster, HistoryMonth, TrainingReport, UploadResult } from './roster/roster.models';
import { RosterService } from './roster/roster.service';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css']
})
export class AppComponent implements OnInit {
  uploadResult: UploadResult;
  history: HistoryMonth[] = [];
  training: TrainingReport;
  roster: GeneratedRoster;

  uploading = false;
  generating = false;
  uploadError: string;
  generateError: string;
  generateReasons: string[] = [];

  options = {
    month: '',
    seed: 42,
    time_limit_seconds: 20,
    min_per_client_shift: 2,
    balance_slack: 1
  };

  constructor(private service: RosterService) {}

  ngOnInit(): void {
    this.refreshHistory();
  }

  refreshHistory(): void {
    this.service.history().subscribe(response => {
      this.history = response.months;
      this.training = response.model;
      if (!this.options.month && this.history.length) {
        this.options.month = this.nextMonth(this.history[this.history.length - 1].month);
      }
    });
  }

  onUpload(event: { file: File; month?: string }): void {
    this.uploading = true;
    this.uploadError = undefined;
    this.service.upload(event.file, event.month).subscribe(
      result => {
        this.uploading = false;
        this.uploadResult = result;
        this.training = result.training;
        this.options.month = result.target_month;
        this.refreshHistory();
      },
      (error: HttpErrorResponse) => {
        this.uploading = false;
        this.uploadError = this.describe(error);
      });
  }

  onRemoveMonth(month: string): void {
    this.service.deleteMonth(month).subscribe(() => this.refreshHistory());
  }

  generate(): void {
    this.generating = true;
    this.generateError = undefined;
    this.generateReasons = [];
    this.service.generate(this.options).subscribe(
      roster => {
        this.generating = false;
        this.roster = roster;
        this.training = roster.meta.training;
      },
      (error: HttpErrorResponse) => {
        this.generating = false;
        const detail = error.error && error.error.detail;
        if (detail && detail.reasons) {
          this.generateError = 'The rules cannot all be met for this team:';
          this.generateReasons = detail.reasons;
        } else {
          this.generateError = this.describe(error);
        }
      });
  }

  get canGenerate(): boolean {
    return !this.generating && (this.history.length > 0 || !!this.uploadResult);
  }

  private nextMonth(month: string): string {
    const [year, number] = month.split('-').map(Number);
    return number === 12 ? `${year + 1}-01` : `${year}-${String(number + 1).padStart(2, '0')}`;
  }

  private describe(error: HttpErrorResponse): string {
    if (error.status === 0) {
      return 'The backend is not reachable. Start it with: uvicorn app.main:app --port 8000';
    }
    const detail = error.error && error.error.detail;
    return typeof detail === 'string' ? detail : `Request failed (${error.status}).`;
  }
}
