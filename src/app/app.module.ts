import { HttpClientModule } from '@angular/common/http';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BrowserModule } from '@angular/platform-browser';

import { AppComponent } from './app.component';
import { ModelPanelComponent } from './roster/model-panel.component';
import { RosterTableComponent } from './roster/roster-table.component';
import { UploadPanelComponent } from './roster/upload-panel.component';

@NgModule({
  declarations: [
    AppComponent,
    UploadPanelComponent,
    ModelPanelComponent,
    RosterTableComponent
  ],
  imports: [
    BrowserModule,
    FormsModule,
    HttpClientModule
  ],
  providers: [],
  bootstrap: [AppComponent]
})
export class AppModule { }
