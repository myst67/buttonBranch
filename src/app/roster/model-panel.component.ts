import { Component, Input } from '@angular/core';

import { ModelMetrics, TrainingReport } from './roster.models';

@Component({
  selector: 'app-model-panel',
  templateUrl: './model-panel.component.html',
  styleUrls: ['./model-panel.component.css']
})
export class ModelPanelComponent {
  @Input() training: TrainingReport;
  @Input() busy = false;

  get models(): Array<{ title: string; what: string; metrics: ModelMetrics }> {
    if (!this.training) {
      return [];
    }
    return [
      {
        title: 'Shift model',
        what: 'which shift each person moves to',
        metrics: this.training.shift_model
      },
      {
        title: 'Week-off model',
        what: 'which days each person gets off',
        metrics: this.training.off_model
      }
    ];
  }

  percent(value: number): string {
    return Math.round((value || 0) * 100) + '%';
  }
}
