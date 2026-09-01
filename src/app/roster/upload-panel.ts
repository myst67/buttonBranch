import { Component, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { HistoryMonth, ParsedEmployee, UploadResult } from './roster.models';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

@Component({
  selector: 'app-upload-panel',
  imports: [FormsModule],
  templateUrl: './upload-panel.html',
  styleUrl: './upload-panel.css',
})
export class UploadPanel {
  readonly result = input<UploadResult | undefined>(undefined);
  readonly history = input<HistoryMonth[]>([]);
  readonly busy = input(false);
  readonly error = input<string | undefined>(undefined);

  readonly upload = output<{ file: File; month?: string }>();
  readonly remove = output<string>();

  protected monthOverride = '';
  protected readonly dragging = signal(false);
  protected readonly fileName = signal('');

  protected onFile(files: FileList | null): void {
    if (!files?.length) {
      return;
    }
    const file = files[0];
    this.fileName.set(file.name);
    this.upload.emit({ file, month: this.monthOverride.trim() || undefined });
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    this.onFile(event.dataTransfer?.files ?? null);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  protected offLabel(employee: ParsedEmployee): string {
    if (employee.off_start === null || !employee.off_length) {
      return 'unknown';
    }
    return Array.from({ length: employee.off_length },
      (_, index) => WEEKDAYS[(employee.off_start! + index) % 7]).join(', ');
  }
}
