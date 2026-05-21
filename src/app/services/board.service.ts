import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface Ticket {
  id: string;
  title: string;
  description: string;
  next_step: string;
  created?: string;
  updated?: string;
}

export interface ColumnData {
  column: string;
  rev: string;
  count: number;
  tickets: Ticket[];
}

export interface Board {
  columns: string[];
  backlog: ColumnData;
  new: ColumnData;
  inprogress: ColumnData;
  testing: ColumnData;
  done: ColumnData;
  [key: string]: any;
}

/**
 * Reads the Cortex Kanban board from the REST API (api.py), which sits on the
 * same board_core that the MCP server edits — so the app and Claude share one
 * source of truth. Write-back (drag & drop) will use PUT /board/{column} with
 * the column's `rev` as If-Match.
 */
@Injectable({ providedIn: 'root' })
export class BoardService {
  readonly base = environment.boardApi;

  constructor(private http: HttpClient) {}

  getBoard(): Observable<Board> {
    return this.http.get<Board>(`${this.base}/board`);
  }

  getColumn(column: string): Observable<ColumnData> {
    return this.http.get<ColumnData>(`${this.base}/board/${column}`);
  }

  /** Emit the board now and then every `ms` milliseconds. */
  pollBoard(ms = 5000): Observable<Board> {
    return timer(0, ms).pipe(switchMap(() => this.getBoard()));
  }
}
