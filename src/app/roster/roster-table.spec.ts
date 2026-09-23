import { ComponentRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';

import { RosterTable } from './roster-table';
import { GeneratedRoster } from './roster.models';

function sheet(): GeneratedRoster {
  const days = [{ label: 'Tue-01-Jul', weekday: 1 }, { label: 'Wed-02-Jul', weekday: 2 }];
  const row = (name: string, clients: string[], shift: string) => ({
    name, clients, client_label: clients.join(', '), shift, previous_shift: null,
    off_start: 0, off_length: 2, cells: [shift, 'Off'], reason: 'because',
    shift_score: 1, off_score: 1, working_days: 1, off_days: 1,
  });
  const cover = (client: string, shift: string) => ({
    client, shift, per_day: [1, 1], min: 1,
  });
  return {
    month: '2025-07', month_label: 'July 2025', days,
    header: ['Name', 'Client', ...days.map((d) => d.label)],
    clients: ['Optiv', 'WSP'],
    rows: [
      row('Asha Kumar', ['Optiv'], 'Morning'),
      row('Ben Doyle', ['WSP'], 'Morning'),
      row('Cara Singh', ['Optiv', 'WSP'], 'Night'),
    ],
    coverage: [cover('Optiv', 'Morning'), cover('Optiv', 'Night'), cover('WSP', 'Morning')],
    meta: {
      id: 'x', generated_at: '', source_month: null, solver_status: 'OPTIMAL',
      solve_seconds: 0, objective: 0, balance_slack_used: 0, notes: [],
      training: { n_history_months: 0, months: [] },
      gaps: { ok: true, needed_per_client: 8, min_per_client_shift: 2,
              clients_short: [], moves: [], unresolved: [], summary: '' },
    },
    validation: { ok: true, schedule_ok: true, fully_covered: true, errors: [],
                  team_shape: [], coverage_gaps: [],
                  checked: { employees: 3, clients: 2, days: 2, client_shift_day_slots: 6 } },
  } as unknown as GeneratedRoster;
}

describe('RosterTable filters', () => {
  let fixture: ComponentFixture<RosterTable>;
  let ref: ComponentRef<RosterTable>;
  let table: any;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RosterTable],
      providers: [provideHttpClient()],
    }).compileComponents();
    fixture = TestBed.createComponent(RosterTable);
    ref = fixture.componentRef;
    ref.setInput('roster', sheet());
    table = fixture.componentInstance as any;
    fixture.detectChanges();
  });

  it('shows every row until a filter is set', () => {
    expect(table.visibleRows().length).toBe(3);
    expect(table.filtering()).toBe(false);
  });

  it('filters by client, including people who serve several', () => {
    table.filterClient.set('WSP');
    expect(table.visibleRows().map((r: any) => r.name)).toEqual(['Ben Doyle', 'Cara Singh']);
  });

  it('filters by shift', () => {
    table.filterShift.set('Night');
    expect(table.visibleRows().map((r: any) => r.name)).toEqual(['Cara Singh']);
  });

  it('matches an employee on part of the name, ignoring case', () => {
    table.filterName.set('  sInGh ');
    expect(table.visibleRows().map((r: any) => r.name)).toEqual(['Cara Singh']);
  });

  it('combines the three filters', () => {
    table.filterClient.set('Optiv');
    table.filterShift.set('Morning');
    table.filterName.set('asha');
    expect(table.visibleRows().map((r: any) => r.name)).toEqual(['Asha Kumar']);

    table.filterShift.set('Night');
    expect(table.visibleRows().length).toBe(0);
  });

  it('narrows the coverage view by client and shift only', () => {
    table.filterClient.set('Optiv');
    table.filterName.set('nobody-by-this-name');
    expect(table.visibleCoverage().length).toBe(2);
    table.filterShift.set('Night');
    expect(table.visibleCoverage().map((e: any) => e.shift)).toEqual(['Night']);
  });

  it('clears back to the full roster', () => {
    table.filterClient.set('WSP');
    table.filterShift.set('Morning');
    table.filterName.set('ben');
    table.clearFilters();
    expect(table.filtering()).toBe(false);
    expect(table.visibleRows().length).toBe(3);
    expect(table.visibleCoverage().length).toBe(3);
  });

  it('leaves the whole-roster stats alone', () => {
    table.filterClient.set('WSP');
    expect(table.headcount('Morning')).toBe(2);
  });
});
