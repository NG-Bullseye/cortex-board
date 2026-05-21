import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { Board, BoardService, ColumnData } from '../services/board.service';

@Component({
  selector: 'app-board',
  templateUrl: 'board.page.html',
  styleUrls: ['board.page.scss'],
  standalone: false,
})
export class BoardPage implements OnInit, OnDestroy {
  board: Board | null = null;
  loading = false;
  error: string | null = null;
  showBacklog = false;
  lastRefresh: Date | null = null;

  // backlog is hidden by default; the rest are always shown left-to-right
  readonly mainColumns = ['new', 'inprogress', 'testing', 'done'];
  readonly columnLabels: { [key: string]: string } = {
    backlog: 'BACKLOG',
    new: 'NEW',
    inprogress: 'IN PROGRESS',
    testing: 'TESTING',
    done: 'DONE',
  };

  private sub?: Subscription;

  constructor(public boardSvc: BoardService) {}

  ngOnInit() {
    this.loading = true;
    this.sub = this.boardSvc.pollBoard(5000).subscribe({
      next: (b) => {
        this.board = b;
        this.loading = false;
        this.error = null;
        this.lastRefresh = new Date();
      },
      error: () => {
        this.loading = false;
        this.error = `Board-API nicht erreichbar (${this.boardSvc.base})`;
      },
    });
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  refresh() {
    this.loading = true;
    this.boardSvc.getBoard().subscribe({
      next: (b) => {
        this.board = b;
        this.loading = false;
        this.error = null;
        this.lastRefresh = new Date();
      },
      error: () => {
        this.loading = false;
        this.error = `Board-API nicht erreichbar (${this.boardSvc.base})`;
      },
    });
  }

  get columns(): string[] {
    return this.showBacklog ? ['backlog', ...this.mainColumns] : this.mainColumns;
  }

  col(name: string): ColumnData | null {
    return this.board ? ((this.board as any)[name] as ColumnData) : null;
  }
}
