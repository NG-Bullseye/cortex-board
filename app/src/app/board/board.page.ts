import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { Board, BoardService, ColumnData, ScanBoard } from '../services/board.service';

@Component({
  selector: 'app-board',
  templateUrl: 'board.page.html',
  styleUrls: ['board.page.scss'],
  standalone: false,
})
export class BoardPage implements OnInit, OnDestroy {
  board: Board | null = null;
  scanBoard: ScanBoard | null = null;
  loading = false;
  error: string | null = null;
  showBacklog = false;
  lastRefresh: Date | null = null;

  /** Which board is currently visible: 'cortex' | 'systemscann' */
  activeBoard: 'cortex' | 'systemscann' = 'cortex';

  // backlog is hidden by default; the rest are always shown left-to-right
  readonly mainColumns = ['new', 'inprogress', 'testing', 'done'];
  readonly columnLabels: { [key: string]: string } = {
    backlog: 'BACKLOG',
    new: 'NEW',
    inprogress: 'IN PROGRESS',
    testing: 'TESTING',
    done: 'DONE',
  };

  readonly scanColumns = ['new', 'open', 'resolved'];
  readonly scanColumnLabels: { [key: string]: string } = {
    new: 'NEW',
    open: 'OPEN',
    resolved: 'RESOLVED',
  };

  private sub?: Subscription;
  private scanSub?: Subscription;

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
    this.scanSub = this.boardSvc.pollScanBoard(5000).subscribe({
      next: (b) => { this.scanBoard = b; },
      error: () => { /* scan board errors are non-fatal */ },
    });
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
    this.scanSub?.unsubscribe();
  }

  refresh() {
    this.loading = true;
    const refreshFn = this.activeBoard === 'systemscann'
      ? this.boardSvc.getScanBoard()
      : this.boardSvc.getBoard();

    if (this.activeBoard === 'systemscann') {
      this.boardSvc.getScanBoard().subscribe({
        next: (b) => {
          this.scanBoard = b;
          this.loading = false;
          this.error = null;
          this.lastRefresh = new Date();
        },
        error: () => {
          this.loading = false;
          this.error = `Scan-Board-API nicht erreichbar (${this.boardSvc.base})`;
        },
      });
    } else {
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
  }

  get columns(): string[] {
    return this.showBacklog ? ['backlog', ...this.mainColumns] : this.mainColumns;
  }

  col(name: string): ColumnData | null {
    return this.board ? ((this.board as any)[name] as ColumnData) : null;
  }

  scanCol(name: string): ColumnData | null {
    return this.scanBoard ? ((this.scanBoard as any)[name] as ColumnData) : null;
  }
}
