import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import SessionList from "./pages/SessionList";
import NewSession from "./pages/NewSession";
import SessionDetail from "./pages/SessionDetail";
import "./index.css";

export default function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <header className="topbar">
          <Link to="/" className="topbar-brand">
            <div className="topbar-mark" aria-hidden="true" />
            ramp agent
          </Link>
          <nav className="topbar-nav" aria-label="Main">
            <Link to="/" className="btn btn-accent">
              Sessions
            </Link>
            <Link to="/new" className="btn btn-accent">
              New Run
            </Link>
          </nav>
        </header>
        <main className="main">
          <Routes>
            <Route path="/" element={<SessionList />} />
            <Route path="/new" element={<NewSession />} />
            <Route path="/sessions/:id" element={<SessionDetail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
