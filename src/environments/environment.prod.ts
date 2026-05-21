export const environment = {
  production: true,
  // empty = same origin: the app is served by the board API itself, so it calls
  // /api/... relative to wherever it is opened (no CORS, no hardcoded host IP).
  boardApi: ''
};
