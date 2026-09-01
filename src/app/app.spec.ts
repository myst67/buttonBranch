import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { App } from './app';

describe('App', () => {
  let fixture: ComponentFixture<App>;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(App);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  /** Renders, answers the startup /api/history call, and lets it settle. */
  async function loadHistory(months: unknown[] = []) {
    fixture.detectChanges();
    http.expectOne('/api/history').flush({ months, model: null });
    await fixture.whenStable();
  }

  it('creates the app', async () => {
    await loadHistory();
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('shows the title', async () => {
    await loadHistory();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain('Monthly roster builder');
  });

  it('walks the user through upload, model and build', async () => {
    await loadHistory();
    const headings = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.panel-head h2'),
      (heading) => heading.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(headings).toEqual([
      "1 Last month's roster",
      '2 What the model has learned',
      '3 Build the month',
    ]);
  });

  it('prefills the month to build from the newest stored month', async () => {
    await loadHistory([
      { month: '2025-11', month_label: 'Nov 2025', employees: 60, clients: 20,
        with_off_pattern: 60, warnings: 0 },
      { month: '2025-12', month_label: 'Dec 2025', employees: 60, clients: 20,
        with_off_pattern: 60, warnings: 0 },
    ]);
    expect(fixture.componentInstance['options'].month).toBe('2026-01');
  });

  it('reports a backend that is not running', async () => {
    await loadHistory();
    const component = fixture.componentInstance;

    const generating = component['generate']();
    http.expectOne('/api/roster/generate').error(new ProgressEvent('offline'), { status: 0 });
    await generating;

    expect(component['generateError']()).toContain('backend is not reachable');
  });
});
