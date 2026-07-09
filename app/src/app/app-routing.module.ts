import { NgModule } from '@angular/core';
import { PreloadAllModules, RouterModule, Routes } from '@angular/router';

const routes: Routes = [
  {
    path: 'board',
    loadChildren: () => import('./board/board.module').then( m => m.BoardPageModule)
  },
  {
    path: 'home',
    loadChildren: () => import('./home/home.module').then( m => m.HomePageModule)
  },
  {
    path: 'docs',
    loadChildren: () => import('./docs/docs.module').then( m => m.DocsPageModule)
  },
  {
    path: 'monitoring',
    loadChildren: () => import('./monitoring/monitoring.module').then( m => m.MonitoringPageModule)
  },
  {
    path: '',
    redirectTo: 'board',
    pathMatch: 'full'
  },
];

@NgModule({
  imports: [
    RouterModule.forRoot(routes, { preloadingStrategy: PreloadAllModules })
  ],
  exports: [RouterModule]
})
export class AppRoutingModule { }
