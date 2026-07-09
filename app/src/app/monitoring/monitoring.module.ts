import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IonicModule } from '@ionic/angular';
import { RouterModule } from '@angular/router';
import { MonitoringPage } from './monitoring.page';

@NgModule({
  imports: [
    CommonModule,
    IonicModule,
    RouterModule.forChild([{ path: '', component: MonitoringPage }]),
  ],
  declarations: [MonitoringPage],
})
export class MonitoringPageModule {}
