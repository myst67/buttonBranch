import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { async, ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';

import { AppComponent } from './app.component';
import { ModelPanelComponent } from './roster/model-panel.component';
import { RosterTableComponent } from './roster/roster-table.component';
import { UploadPanelComponent } from './roster/upload-panel.component';

describe('AppComponent', () => {
  let fixture: ComponentFixture<AppComponent>;
  let http: HttpTestingController;

  beforeEach(async(() => {
    TestBed.configureTestingModule({
      imports: [FormsModule, HttpClientTestingModule],
      declarations: [AppComponent, UploadPanelComponent, ModelPanelComponent, RosterTableComponent]
    }).compileComponents();
  }));

  beforeEach(() => {
    fixture = TestBed.createComponent(AppComponent);
    http = TestBed.get(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('creates the app', () => {
    fixture.detectChanges();
    http.expectOne('/api/history').flush({ months: [], model: null });
    expect(fixture.debugElement.componentInstance).toBeTruthy();
  });

  it('shows the title', () => {
    fixture.detectChanges();
    http.expectOne('/api/history').flush({ months: [], model: null });
    fixture.detectChanges();
    const compiled = fixture.debugElement.nativeElement;
    expect(compiled.querySelector('h1').textContent).toContain('Monthly roster builder');
  });

  it('prefills the month to build from the newest stored month', () => {
    fixture.detectChanges();
    http.expectOne('/api/history').flush({
      months: [{ month: '2025-12', month_label: 'Dec 2025', employees: 23, clients: 6,
                 with_off_pattern: 23, warnings: 0 }],
      model: null
    });
    expect(fixture.componentInstance.options.month).toBe('2026-01');
  });

  it('reports a backend that is not running', () => {
    const component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne('/api/history').flush({ months: [], model: null });

    component.generate();
    http.expectOne('/api/roster/generate').error(new ErrorEvent('offline'), { status: 0 });
    expect(component.generateError).toContain('backend is not reachable');
  });
});
