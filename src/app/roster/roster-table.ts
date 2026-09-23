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

  // View filters. They narrow what the table shows and nothing else: the stats
  // above describe the whole roster, and the downloads always carry all of it.
  protected readonly filterClient = signal('');
  protected readonly filterShift = signal('');
  protected readonly filterName = signal('');

  /** Every client in the roster, for the client picker. */
  protected readonly clients = computed(() => this.roster()?.clients ?? []);

  protected readonly filtering = computed(
    () => !!(this.filterClient() || this.filterShift() || this.filterName().trim()));

  protected readonly visibleRows = computed(() => {
    const rows = this.roster()?.rows ?? [];
    const client = this.filterClient();
    const shift = this.filterShift();
    const name = this.filterName().trim().toLowerCase();
    return rows.filter((row) =>
      (!client || row.clients.includes(client)) &&
      (!shift || row.shift === shift) &&
      (!name || row.name.toLowerCase().includes(name)));
  });

  /** The coverage view honours client and shift; a person's name is not in it. */
  protected readonly visibleCoverage = computed(() => {
    const coverage = this.roster()?.coverage ?? [];
    const client = this.filterClient();
    const shift = this.filterShift();
    return coverage.filter((entry) =>
      (!client || entry.client === client) && (!shift || entry.shift === shift));
  });

  protected clearFilters(): void {
    this.filterClient.set('');
    this.filterShift.set('');
    this.filterName.set('');
  }

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
