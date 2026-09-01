import { Component, computed, input } from '@angular/core';

import { ModelMetrics, TrainingReport } from './roster.models';

interface ModelCard {
  title: string;
  what: string;
  metrics: ModelMetrics;
}

@Component({
  selector: 'app-model-panel',
  templateUrl: './model-panel.html',
  styleUrl: './model-panel.css',
})
export class ModelPanel {
  readonly training = input<TrainingReport | undefined>(undefined);

  protected readonly models = computed<ModelCard[]>(() => {
    const report = this.training();
    if (!report) {
      return [];
    }
    return [
      {
        title: 'Shift model',
        what: 'which shift each person moves to',
        metrics: report.shift_model,
      },
      {
        title: 'Week-off model',
        what: 'which days each person gets off',
        metrics: report.off_model,
      },
    ];
  });

  protected percent(value: number | null): string {
    return `${Math.round((value ?? 0) * 100)}%`;
  }
}
