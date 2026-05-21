import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IonicModule } from '@ionic/angular';
import { FormsModule } from '@angular/forms';

import { BoardPage } from './board.page';
import { BoardPageRoutingModule } from './board-routing.module';

@NgModule({
  imports: [CommonModule, FormsModule, IonicModule, BoardPageRoutingModule],
  declarations: [BoardPage],
})
export class BoardPageModule {}
