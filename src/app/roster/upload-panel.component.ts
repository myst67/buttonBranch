import { Component, EventEmitter, Input, Output } from '@angular/core';

import { HistoryMonth, UploadResult } from './roster.models';

@Component({
  selector: 'app-upload-panel',
  templateUrl: './upload-panel.component.html',
  styleUrls: ['./upload-panel.component.css']
})
export class UploadPanelComponent {
  @Input() result: UploadResult;
  @Input() history: HistoryMonth[] = [];
  @Input() busy = false;
  @Input() error: string;

  @Output() upload = new EventEmitter<{ file: File; month?: string }>();
  @Output() remove = new EventEmitter<string>();

  monthOverride = '';
  dragging = false;
  fileName = '';

  onFile(files: FileList): void {
    if (!files || !files.length) {
      return;
    }
    const file = files.item(0);
    this.fileName = file.name;
    this.upload.emit({ file, month: this.monthOverride ? this.monthOverride.trim() : undefined });
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging = false;
    this.onFile(event.dataTransfer.files);
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging = true;
  }

  offLabel(employee: { off_start: number | null; off_length: number | null }): string {
    if (employee.off_start === null || !employee.off_length) {
      return 'unknown';
    }
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const block: string[] = [];
    for (let i = 0; i < employee.off_length; i++) {
      block.push(days[(employee.off_start + i) % 7]);
    }
    return block.join(', ');
  }
}
