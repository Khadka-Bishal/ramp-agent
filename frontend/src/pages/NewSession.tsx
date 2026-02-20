import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export default function NewSession() {
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [prompt, setPrompt] = useState('');

  const canSubmit = repoUrl.trim() !== '' && prompt.trim() !== '' && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;

    setSubmitting(true);
    try {
      const { id } = await api.createSession({
        repo_url: repoUrl.trim(),
        prompt: prompt.trim(),
      });
      await api.triggerRun(id);
      navigate(`/sessions/${id}`);
    } catch (err) {
      console.error('Create failed:', err);
      setSubmitting(false);
    }
  }

  return (
    <div className="page" style={{ maxWidth: 580 }}>
      <h1 style={{ marginBottom: '0.5rem' }}>New Run</h1>
      <p style={{ color: 'var(--text-2)', marginBottom: '1.5rem', fontSize: '0.8125rem' }}>
        Point at a repo, describe what you need. The agent handles the rest.
      </p>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <div className="field">
          <label className="label" htmlFor="repo_url">Repository</label>
          <input
            id="repo_url"
            className="input"
            type="url"
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            required
          />
        </div>

        <div className="field">
          <label className="label" htmlFor="prompt">What should change?</label>
          <textarea
            id="prompt"
            className="textarea"
            placeholder="Add a /health endpoint that returns { status: 'ok' }..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={5}
            required
          />
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem' }}>
          <button type="submit" className="btn btn-accent" disabled={!canSubmit}>
            {submitting ? 'Starting…' : 'Create & Run'}
          </button>
          <button type="button" className="btn btn-outline" onClick={() => navigate('/')}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
