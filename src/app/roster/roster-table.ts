import { Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { GeneratedRoster } from './roster.models';
import { RosterService } from './roster.service';

const SHIFTS = ['Morning', 'Afternoon', 'Evening', 'Night'];

@Component({
  selector: 'app-roster-table',
  imports: [FormsModule],
  templateUrl: './roster-table.html',
  styleUrl: './roster-table.css',
})
export class RosterTable {
  private readonly service = inject(RosterService);

  readonly roster = input<GeneratedRoster | undefined>(undefined);

  protected showWhy = false;
  protected readonly view = signal<'roster' | 'coverage'>('roster');
  protected readonly shifts = SHIFTS;

  /** The thinnest client/shift/day cover anywhere in the month - rule 5 at a glance. */
  protected readonly minimumCover = computed(() =>
    this.roster()?.coverage.reduce((min, row) => Math.min(min, row.min), Infinity) ?? 0);

  protected readonly slotsWithSpare = computed(() =>
    this.roster()?.coverage.reduce(
      (total, row) => total + row.per_day.filter((count) => count > 1).length, 0) ?? 0);

  protected readonly totalSlots = computed(() => {
    const roster = this.roster();
    return roster ? roster.coverage.length * roster.days.length : 0;
  });

  protected headcount(shift: string): number {
    return this.roster()?.rows.filter((row) => row.shift === shift).length ?? 0;
  }

  protected isWeekend(index: number): boolean {
    return (this.roster()?.days[index].weekday ?? 0) >= 5;
  }

  protected exportUrl(format: 'xlsx' | 'csv'): string {
    const roster = this.roster();
    return roster ? this.service.exportUrl(roster.meta.id, format) : '';
  }
}
