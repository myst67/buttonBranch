import { Component, Input } from '@angular/core';

import { GeneratedRoster } from './roster.models';
import { RosterService } from './roster.service';

@Component({
  selector: 'app-roster-table',
  templateUrl: './roster-table.component.html',
  styleUrls: ['./roster-table.component.css']
})
export class RosterTableComponent {
  @Input() roster: GeneratedRoster;

  showWhy = false;
  view: 'roster' | 'coverage' = 'roster';

  constructor(private service: RosterService) {}

  get shifts(): string[] {
    return ['Morning', 'Afternoon', 'Evening', 'Night'];
  }

  headcount(shift: string): number {
    return this.roster.rows.filter(row => row.shift === shift).length;
  }

  /** The thinnest client/shift/day cover anywhere in the month - rule 5 at a glance. */
  get minimumCover(): number {
    return this.roster.coverage.reduce((min, row) => Math.min(min, row.min), Infinity);
  }

  get slotsWithSpare(): number {
    return this.roster.coverage.reduce(
      (total, row) => total + row.per_day.filter(count => count > 1).length, 0);
  }

  get totalSlots(): number {
    return this.roster.coverage.length * this.roster.days.length;
  }

  isWeekend(index: number): boolean {
    return this.roster.days[index].weekday >= 5;
  }

  exportUrl(format: 'xlsx' | 'csv'): string {
    return this.service.exportUrl(this.roster.meta.id, format);
  }
}
