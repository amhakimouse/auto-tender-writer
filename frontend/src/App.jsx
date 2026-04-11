import { useState } from 'react'
import axios from 'axios'
import { Upload, CheckCircle2, AlertCircle, FileText, Info, ArrowRight, Download, Eye } from 'lucide-react'

// --- Components ---

function Header() {
  return (
    <header style={{ padding: '24px 48px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{ width: '40px', height: '40px', background: 'var(--primary)', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white' }}>
          <FileText size={24} />
        </div>
        <h1 style={{ margin: 0, fontSize: '24px' }}>Tender<span style={{ color: 'var(--primary)' }}>AI</span></h1>
      </div>
      <div style={{ display: 'flex', gap: '24px', color: 'var(--text-muted)', fontWeight: 500 }}>
        <span>Dashboard</span>
        <span>History</span>
        <span>Settings</span>
      </div>
    </header>
  )
}

function UploadView({ onAnalyze }) {
  const [file, setFile] = useState(null)
  const [profile, setProfile] = useState('')

  const handleSubmit = () => {
    if (file && profile) {
      onAnalyze(file, profile)
    }
  }

  return (
    <main style={{ maxWidth: '800px', margin: '40px auto', padding: '0 24px' }} className="animate-fade-in">
      <div style={{ textAlign: 'center', marginBottom: '48px' }}>
        <h2 style={{ fontSize: '48px', marginBottom: '16px' }}>Automate Your Tender Responses</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: '18px' }}>Upload your tender PDF and company profile to generate a compliant, high-quality dossier in seconds.</p>
      </div>

      <div className="glass-card" style={{ padding: '40px' }}>
        <div style={{ marginBottom: '32px' }}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '12px' }}>Tender Document (PDF)</label>
          <div 
            style={{ 
              border: '2px dashed var(--border-color)', 
              borderRadius: '16px', 
              padding: '40px', 
              textAlign: 'center',
              backgroundColor: file ? 'rgba(0, 97, 255, 0.05)' : 'transparent',
              borderColor: file ? 'var(--primary)' : 'var(--border-color)',
              cursor: 'pointer'
            }}
            onClick={() => document.getElementById('fileInput').click()}
          >
            <input 
              id="fileInput" 
              type="file" 
              accept=".pdf" 
              style={{ display: 'none' }} 
              onChange={(e) => setFile(e.target.files[0])}
            />
            <Upload size={48} color={file ? 'var(--primary)' : 'var(--text-muted)'} style={{ marginBottom: '16px' }} />
            <p style={{ margin: 0, fontWeight: 500 }}>{file ? file.name : "Click to upload or drag and drop"}</p>
            <p style={{ margin: '8px 0 0', fontSize: '14px', color: 'var(--text-muted)' }}>PDF up to 10MB</p>
          </div>
        </div>

        <div style={{ marginBottom: '32px' }}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '12px' }}>Company Profile</label>
          <textarea 
            placeholder="Tell us about your company, references, and certifications..."
            style={{ 
              width: '100%', 
              height: '120px', 
              padding: '16px', 
              borderRadius: '12px', 
              border: '1px solid var(--border-color)',
              fontFamily: 'inherit',
              fontSize: '16px',
              resize: 'none',
              boxSizing: 'border-box'
            }}
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
          />
        </div>

        <button 
          className="btn-primary" 
          style={{ width: '100%', justifyContent: 'center', height: '56px', fontSize: '18px' }}
          disabled={!file || !profile}
          onClick={handleSubmit}
        >
          Start Analysis <ArrowRight size={20} />
        </button>
      </div>
    </main>
  )
}

function ProcessingView() {
  return (
    <main style={{ maxWidth: '600px', margin: '100px auto', padding: '0 24px' }}>
      <div className="glass-card" style={{ padding: '40px' }}>
        <h3 style={{ fontSize: '24px', marginBottom: '32px', textAlign: 'center' }}>AI Engine Processing</h3>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div className="step-item completed">
            <div className="step-indicator"><CheckCircle2 size={20} /></div>
            <div>
              <div style={{ fontWeight: 600 }}>Parsing PDF Document</div>
              <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Text and layout extraction completed.</div>
            </div>
          </div>
          <div className="step-item active">
            <div className="step-indicator"><div style={{ width: '8px', height: '8px', background: 'white', borderRadius: '50%' }}></div></div>
            <div>
              <div style={{ fontWeight: 600 }}>Extracting Requirements</div>
              <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Identifying administrative and technical criteria...</div>
            </div>
          </div>
          <div className="step-item">
            <div className="step-indicator" />
            <div>
              <div style={{ fontWeight: 600 }}>Generating Response Dossier</div>
              <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Drafting note de présentation and methodology.</div>
            </div>
          </div>
          <div className="step-item">
            <div className="step-indicator" />
            <div>
              <div style={{ fontWeight: 600 }}>Validating Compliance</div>
              <div style={{ fontSize: '14px', color: 'var(--text-muted)' }}>Mistral-v0.3 auditing the generated content.</div>
            </div>
          </div>
        </div>

        <div style={{ marginTop: '40px', textAlign: 'center' }}>
          <div style={{ width: '100%', height: '4px', background: 'var(--border-color)', borderRadius: '2px', overflow: 'hidden' }}>
            <div style={{ width: '45%', height: '100%', background: 'var(--primary)', animation: 'progress 2s infinite ease-in-out' }}></div>
          </div>
          <p style={{ marginTop: '16px', color: 'var(--text-muted)', fontSize: '14px' }}>Estimated time: 30-45 seconds</p>
        </div>
      </div>
      
      <style>{`
        @keyframes progress {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(200%); }
        }
      `}</style>
    </main>
  )
}

function ResultsView({ data }) {
  const score = data.validation.compliance_score || 0
  const getColor = (s) => s > 70 ? 'var(--success)' : s > 40 ? 'var(--warning)' : 'var(--error)'

  return (
    <main style={{ maxWidth: '1200px', margin: '40px auto', padding: '0 24px' }} className="animate-fade-in">
      {/* Upper Summary */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '32px', marginBottom: '32px' }}>
        <div className="glass-card" style={{ padding: '32px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ position: 'relative', width: '160px', height: '160px', marginBottom: '24px' }}>
            <svg viewBox="0 0 36 36" style={{ width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
              <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#E2E8F0" strokeWidth="3" />
              <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke={getColor(score)} strokeWidth="3" strokeDasharray={`${score}, 100`} strokeLinecap="round" />
            </svg>
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }}>
              <div style={{ fontSize: '36px', fontWeight: 800 }}>{score}%</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>COMPLIANCE</div>
            </div>
          </div>
          <div style={{ backgroundColor: getColor(score) + '15', color: getColor(score), padding: '8px 16px', borderRadius: '20px', fontWeight: 700, fontSize: '14px' }}>
            {data.validation.verdict}
          </div>
        </div>

        <div className="glass-card" style={{ padding: '32px' }}>
          <h3 style={{ marginTop: 0, fontSize: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <CheckCircle2 size={24} color="var(--success)" /> Validation Results
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginTop: '24px' }}>
            <div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '12px' }}>MANDATORY SECTIONS FOUND</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {data.validation.sections_compliant.map((s, i) => (
                  <span key={i} style={{ background: '#F1F5F9', padding: '4px 12px', borderRadius: '6px', fontSize: '13px' }}>{s}</span>
                ))}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--warning)', marginBottom: '12px' }}>REQUIRED ADJUSTMENTS</div>
              <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '13px', color: 'var(--text-muted)' }}>
                {data.validation.recommendations.map((r, i) => (
                  <li key={i} style={{ marginBottom: '4px' }}>{r}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* Dual View Editor */}
      <div className="glass-card" style={{ display: 'grid', gridTemplateColumns: '350px 1fr', height: '600px', overflow: 'hidden' }}>
        <div style={{ borderRight: '1px solid var(--border-color)', padding: '24px', overflowY: 'auto', backgroundColor: 'rgba(0,0,0,0.02)' }}>
          <h4 style={{ marginTop: 0, marginBottom: '20px', fontSize: '16px' }}>Requirements Extracted</h4>
          {data.requirements.administrative_documents?.map((doc, i) => (
            <div key={i} style={{ padding: '12px', background: 'white', borderRadius: '10px', marginBottom: '12px', fontSize: '13px', boxShadow: '0 2px 4px rgba(0,0,0,0.02)' }}>
              {doc}
            </div>
          ))}
          <div style={{ padding: '12px', background: 'rgba(0,97,255,0.05)', borderRadius: '10px', marginTop: '20px' }}>
            <div style={{ fontSize: '12px', color: 'var(--primary)', fontWeight: 700, marginBottom: '4px' }}>SELECTION CRITERIA</div>
            <p style={{ margin: 0, fontSize: '13px' }}>{data.requirements.selection_criteria?.join(', ')}</p>
          </div>
        </div>
        
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', gap: '16px' }}>
              <button disabled style={{ background: 'white', border: '1px solid var(--border-color)', padding: '8px 16px', borderRadius: '8px', fontSize: '14px', fontWeight: 600 }}>Edit Draft</button>
              <button style={{ background: 'var(--primary)', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '8px', fontSize: '14px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Download size={16} /> Export PDF
              </button>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Refined by Mistral-Large</div>
          </div>
          <div style={{ padding: '40px', overflowY: 'auto', lineHeight: '1.6' }}>
            <h1 style={{ textAlign: 'center', marginBottom: '48px' }}>OFFRE TECHNIQUE</h1>
            <section style={{ marginBottom: '32px' }}>
              <h3>Note de Présentation</h3>
              <p>{data.dossier.presentation_note}</p>
            </section>
            <section style={{ marginBottom: '32px' }}>
              <h3>Références Similaires</h3>
              <p>{data.dossier.similar_references_note}</p>
            </section>
            <section style={{ marginBottom: '32px' }}>
              <h3>Méthodologie d'Exécution</h3>
              <p>{data.dossier.execution_methodology}</p>
            </section>
            <section style={{ marginBottom: '32px' }}>
              <h3>Planning Prévisionnel</h3>
              <p>{data.dossier.preliminary_schedule}</p>
            </section>
            <section style={{ marginBottom: '32px' }}>
              <h3>Détails Techniques</h3>
              <p>{data.dossier.technical_offer_details}</p>
            </section>
          </div>
        </div>
      </div>
    </main>
  )
}

// --- Main App ---

export default function App() {
  const [view, setView] = useState('IDLE') // IDLE, PROCESSING, RESULT
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  const handleAnalyze = async (file, profile) => {
    setView('PROCESSING')
    setError(null)

    const formData = new FormData()
    formData.append('file', file)
    // Wrap the raw text in a JSON object as expected by the backend intake.py
    const profileJson = JSON.stringify({
      company_name: "My Enterprise",
      description: profile,
      contact_email: "contact@enterprise.com"
    })
    formData.append('company_profile', profileJson)

    try {
      const response = await axios.post('/api/v1/intake/analyze', formData)
      setData(response.data)
      setView('RESULT')
    } catch (err) {
      console.error(err)
      setError("Analysis failed. Please try again.")
      setView('IDLE')
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header />
      
      {view === 'IDLE' && <UploadView onAnalyze={handleAnalyze} />}
      {view === 'PROCESSING' && <ProcessingView />}
      {view === 'RESULT' && data && <ResultsView data={data} />}

      {error && (
        <div style={{ position: 'fixed', bottom: '24px', right: '24px', background: 'var(--error)', color: 'white', padding: '16px 24px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '12px' }} className="animate-fade-in">
          <AlertCircle size={20} /> {error}
        </div>
      )}
    </div>
  )
}
