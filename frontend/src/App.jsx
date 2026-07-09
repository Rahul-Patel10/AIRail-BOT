import React, { useState, useEffect, useRef } from 'react';
import { 
  Send, Mic, MicOff, Volume2, VolumeX, Eye, Info, RefreshCw, 
  MapPin, Calendar, Clock, Compass, Bell, CheckCircle, AlertTriangle, AlertCircle, Sparkles
} from 'lucide-react';
import './App.css';

// Simple Inline Markdown Parser to avoid external dependencies and errors
const parseInlineBold = (text) => {
  const parts = text.split(/(\*\*.*?\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} style={{ color: '#fff', fontWeight: '600' }}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
};

const renderMarkdown = (text) => {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let currentTable = null;
  let currentList = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    if (!line) {
      if (currentList) {
        elements.push(<ul key={`list-${i}`} className="ui-list">{currentList}</ul>);
        currentList = null;
      }
      continue;
    }

    // Table detection
    if (line.startsWith('|')) {
      if (currentList) {
        elements.push(<ul key={`list-${i}`} className="ui-list">{currentList}</ul>);
        currentList = null;
      }

      const cells = line.split('|').map(c => c.trim()).filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
      
      // Divider line detection
      if (line.includes('---')) {
        continue;
      }

      if (!currentTable) {
        currentTable = { headers: cells, rows: [] };
      } else {
        currentTable.rows.push(cells);
      }
      continue;
    } else if (currentTable) {
      // Flush table
      elements.push(
        <div key={`table-${i}`} className="table-container animate-fade-in">
          <table>
            <thead>
              <tr>
                {currentTable.headers.map((h, idx) => <th key={idx}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {currentTable.rows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => <td key={cIdx}>{parseInlineBold(cell)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      currentTable = null;
    }

    // List detection
    if (line.startsWith('•') || line.startsWith('-') || line.startsWith('*')) {
      const cleanItem = line.replace(/^[•\-\*]\s*/, '');
      if (!currentList) {
        currentList = [];
      }
      currentList.push(<li key={`li-${i}`}>{parseInlineBold(cleanItem)}</li>);
      continue;
    } else if (currentList) {
      elements.push(<ul key={`list-${i}`} className="ui-list">{currentList}</ul>);
      currentList = null;
    }

    // Heading detection
    if (line.startsWith('#')) {
      const match = line.match(/^(#+)\s*(.*)/);
      if (match) {
        const level = match[1].length;
        const headingText = match[2];
        const Comp = level === 1 ? 'h1' : level === 2 ? 'h2' : 'h3';
        elements.push(
          <Comp key={i} className={`ui-h${level}`}>
            {parseInlineBold(headingText)}
          </Comp>
        );
        continue;
      }
    }

    // Normal paragraph line
    elements.push(<p key={i} className="ui-para">{parseInlineBold(line)}</p>);
  }

  // Flush remaining table or lists
  if (currentTable) {
    elements.push(
      <div key={`table-final`} className="table-container">
        <table>
          <thead>
            <tr>
              {currentTable.headers.map((h, idx) => <th key={idx}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {currentTable.rows.map((row, rIdx) => (
              <tr key={rIdx}>
                {row.map((cell, cIdx) => <td key={cIdx}>{parseInlineBold(cell)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (currentList) {
    elements.push(<ul key={`list-final`} className="ui-list">{currentList}</ul>);
  }

  return elements;
};

// Main Component
export default function App() {
  const [sessionId] = useState(() => {
    const existingId = localStorage.getItem('railassist_session_id');
    if (existingId) return existingId;

    const newId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
    localStorage.setItem('railassist_session_id', newId);
    return newId;
  });
  const storageKey = `railassist_messages_${sessionId}`;
  const [messages, setMessages] = useState(() => {
    const savedMessages = localStorage.getItem(storageKey);
    if (savedMessages) {
      try {
        return JSON.parse(savedMessages);
      } catch (_e) {
        localStorage.removeItem(storageKey);
      }
    }
    return [];
  });
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [watchlist, setWatchlist] = useState([]);
  const [watchlistError, setWatchlistError] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const [activeTrace, setActiveTrace] = useState([]);
  const [activeSources, setActiveSources] = useState([]);
  const [inAppAlerts, setInAppAlerts] = useState([]);

  const chatEndRef = useRef(null);
  const recognitionRef = useRef(null);
  const wsRef = useRef(null);

  // Initialize Speech Recognition
  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const rec = new SpeechRecognition();
      rec.continuous = false;
      rec.lang = 'en-IN'; // Supports English / Hindi inputs
      rec.interimResults = false;

      rec.onstart = () => setIsListening(true);
      rec.onend = () => setIsListening(false);
      rec.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        setInput(transcript);
      };
      recognitionRef.current = rec;
    }
    
    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }, []);

  // Initialize WebSockets and load Watchlist
  useEffect(() => {
    let isActive = true;
    let reconnectTimer = null;

    // 1. WebSocket Connect
    const connectWs = () => {
      if (!isActive) return;
      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${wsProtocol}://${window.location.host}/api/ws/${sessionId}`);
      
      ws.onopen = () => {
        if (!isActive) return;
        setWsConnected(true);
        console.log('[WS] Connected to backend');
      };
      
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'pnr_alert') {
          // Add to in-app alerts list
          const alertId = Date.now();
          const alertMsg = `PNR ${data.pnr} booking status shifted from ${data.old_status} to ${data.new_status}!`;
          setInAppAlerts(prev => [...prev, { id: alertId, msg: alertMsg, name: data.passenger_name }]);
          
          // Trigger browser notification
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(`🚂 PNR Status Alert!`, {
              body: `${data.passenger_name}: PNR ${data.pnr} is now ${data.new_status} (Seat: ${data.coach}-${data.seat_no})`,
            });
          }
          
          // Refresh watchlist
          fetchWatchlist();
        }
      };

      ws.onclose = () => {
        if (!isActive) return;
        setWsConnected(false);
        console.log('[WS] Disconnected. Reconnecting in 5s...');
        reconnectTimer = setTimeout(connectWs, 5000);
      };

      wsRef.current = ws;
    };

    connectWs();
    fetchWatchlist();

    return () => {
      isActive = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  }, [sessionId]);

  // Scroll to bottom on new message
  useEffect(() => {
    if (messages.length === 0) {
      localStorage.removeItem(storageKey);
      return;
    }
    localStorage.setItem(storageKey, JSON.stringify(messages));
  }, [messages, storageKey]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const fetchWatchlist = async () => {
    try {
      const res = await fetch(`/api/pnr-watchlist/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data);
        setWatchlistError('');
      } else {
        setWatchlistError(`Watchlist load failed (${res.status})`);
      }
    } catch (err) {
      setWatchlistError('Watchlist load failed');
      console.error('Failed to fetch watchlist:', err);
    }
  };

  const startSpeechRecognition = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.start();
      } catch (e) {
        recognitionRef.current.stop();
      }
    } else {
      alert('Speech Recognition is not supported in this browser. Try Chrome/Edge.');
    }
  };

  const stopSpeechRecognition = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  };

  const handleSpeech = (text) => {
    if (!ttsEnabled) return;
    // Strip markdown chars for cleaner reading
    const cleanText = text.replace(/[*#`•\-]/g, '');
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = 'en-IN';
    window.speechSynthesis.speak(utterance);
  };

  const clearChat = () => {
    localStorage.removeItem(storageKey);
    setMessages([]);
    setActiveTrace([]);
    setActiveSources([]);
    setInAppAlerts([]);
  };

  const sendMessage = async (textToSend) => {
    const messageText = textToSend || input;
    if (!messageText.trim()) return;

    setInput('');
    setLoading(true);

    const userMsg = { role: 'user', content: messageText };
    const historyBeforeSend = messages.map(m => ({ role: m.role, content: m.content }));
    const historyWithUserMessage = [...historyBeforeSend, { role: 'user', content: messageText }];

    setMessages(prev => [...prev, userMsg]);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
          history: historyWithUserMessage
        })
      });

      if (res.ok) {
        const data = await res.json();
        const assistantMsg = {
          role: 'assistant',
          content: data.response,
          intent: data.intent,
          trace_steps: data.trace_steps,
          raw_data: data.raw_data,
          sources: data.sources || []
        };
        setMessages(prev => [...prev, assistantMsg]);
        setActiveTrace(data.trace_steps || []);
        setActiveSources(data.sources || []);
        handleSpeech(data.response);
        
        // Refresh watchlist in case a PNR was watched
        if (data.intent === 'prs') {
          fetchWatchlist();
        }
      } else {
        throw new Error('API failed');
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Apologies, I encountered a communication error with the backend server. Please verify the API is running locally.',
        intent: 'guardrail',
        trace_steps: ['[Network Error] API post failed.']
      }]);
    } finally {
      setLoading(false);
    }
  };

  const removeAlert = (alertId) => {
    setInAppAlerts(prev => prev.filter(a => a.id !== alertId));
  };

  // Timeline UI Renderer
  const renderRouteTimeline = (schedule) => {
    if (!schedule || !schedule.stops || schedule.stops.length === 0) return null;
    
    return (
      <div className="svg-timeline animate-fade-in">
        <h4 className="timeline-title">🚂 Route Timeline for {schedule.train_name} ({schedule.train_no})</h4>
        <div className="timeline-scroll">
          <svg className="svg-canvas" height="90" width={schedule.stops.length * 150 + 50}>
            {/* Horizontal Line */}
            <line x1="40" y1="45" x2={schedule.stops.length * 150 - 110} y2="45" stroke="#263147" strokeWidth="4" />
            
            {schedule.stops.map((stop, idx) => {
              const cx = 40 + idx * 150;
              return (
                <g key={idx}>
                  <circle cx={cx} cy="45" r="8" fill={idx === 0 ? '#6366f1' : '#06b6d4'} className="timeline-node" />
                  <text x={cx} y="25" textAnchor="middle" fill="#f3f4f6" fontSize="11" fontWeight="500">{stop.station_code}</text>
                  <text x={cx} y="68" textAnchor="middle" fill="#9ca3af" fontSize="9">{stop.arrival === '--:--' ? stop.departure : stop.arrival}</text>
                  <text x={cx} y="80" textAnchor="middle" fill="#6b7280" fontSize="8">{stop.distance_km} km</text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
    );
  };

  return (
    <div className="dashboard-layout">
      {/* ── LEFT PANEL: Watchlists & System Alerts ── */}
      <aside className="left-panel">
        <div className="panel-header">
          <div className="logo">
            <Compass className="accent-icon" />
            <h2>RailAssist</h2>
          </div>
          <div className={`connection-badge ${wsConnected ? 'connected' : 'disconnected'}`}>
            <span className="dot"></span>
            {wsConnected ? 'Connected' : 'Offline'}
          </div>
        </div>

        {/* Watchlist Section */}
        <div className="panel-section">
          <div className="section-title">
            <Bell size={16} />
            <h3>Active PNR Watchlist</h3>
          </div>
          
          {watchlist.length === 0 ? (
            <div className="empty-state">
              <p>{watchlistError || 'No PNRs in watchlist. Ask to watch a PNR to receive status updates here.'}</p>
            </div>
          ) : (
            <div className="watchlist-list">
              {watchlist.map((w, idx) => (
                <div key={idx} className="watchlist-card animate-fade-in">
                  <div className="card-top">
                    <span className="train-badge">{w.train_no}</span>
                    <span className="pnr-number">{w.pnr}</span>
                  </div>
                  <div className="card-info">
                    <p><strong>Passenger:</strong> {w.passenger_name}</p>
                    <p><strong>Travel:</strong> {w.travel_date}</p>
                  </div>
                  <div className="card-status-row">
                    <div className="status-item">
                      <span className="lbl">Initial:</span>
                      <span className="val badge-wl">{w.last_status}</span>
                    </div>
                    <div className="status-item">
                      <span className="lbl">Current:</span>
                      <span className={`val ${w.current_status === 'CNF' ? 'badge-cnf' : 'badge-wl'}`}>
                        {w.current_status}
                      </span>
                    </div>
                  </div>
                  {w.current_status === 'CNF' && (
                    <div className="seat-info-pill">
                      Allocated: Coach {w.coach}, Seat {w.seat_no}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Quick Prompts Helper */}
        <div className="panel-section quick-actions">
          <div className="section-title">
            <Sparkles size={16} />
            <h3>Quick Travel Queries</h3>
          </div>
          <button className="prompt-btn" onClick={() => sendMessage("Find trains from New Delhi to MumbaiCentral on 2026-06-20")}>
            📍 Search NDLS to BCT
          </button>
          <button className="prompt-btn" onClick={() => sendMessage("Check details for PNR 2145678903")}>
            🎟️ Check PNR 2145678903 (Waitlist)
          </button>
          <button className="prompt-btn" onClick={() => sendMessage("What are the cancellation charges for confirmed tickets?")}>
            📋 IRCTC Ticket Refund Policy
          </button>
        </div>
      </aside>

      {/* ── CENTER PANEL: Main Conversation ── */}
      <main className="center-panel">
        <header className="chat-header">
          <div className="chat-title">
            <h3>Indian Railway AI Assistant</h3>
            <p>100% Offline Hybrid Search & Supervisor Subagent Engine</p>
          </div>
          <div className="chat-actions">
            <button
              className="clear-chat-btn"
              onClick={clearChat}
              title="Clear chat history"
            >
              Clear
            </button>
            <button 
              className={`tts-btn ${ttsEnabled ? 'active' : ''}`}
              onClick={() => setTtsEnabled(!ttsEnabled)}
              title="Toggle read aloud replies"
            >
              {ttsEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}
            </button>
          </div>
        </header>

        {/* In-app Slide alert notifications */}
        {inAppAlerts.map(alert => (
          <div key={alert.id} className="in-app-toast alert-success animate-fade-in">
            <CheckCircle size={18} />
            <div className="toast-content">
              <strong>Waitlist Cleared!</strong>
              <p>{alert.msg}</p>
            </div>
            <button className="close-toast" onClick={() => removeAlert(alert.id)}>x</button>
          </div>
        ))}

        {/* Message Thread */}
        <div className="message-thread">
          {messages.length === 0 && !loading && (
            <div className="welcome-hero animate-fade-in">
              <div className="hero-badge">🚆 Railway Copilot</div>
              <h2>Ask anything about trains, PNRs and travel plans.</h2>
              <p>Search routes, check live-ish updates, and get quick help in one polished workspace.</p>
              <div className="hero-prompt-grid">
                <button onClick={() => sendMessage('Find trains from New Delhi to Mumbai Central today after 5 pm')}>
                  Search trains by time
                </button>
                <button onClick={() => sendMessage('Check PNR 2145678903')}>
                  Check PNR status
                </button>
                <button onClick={() => sendMessage('Watch PNR 2145678903')}>
                  Watch PNR updates
                </button>
              </div>
            </div>
          )}

          {messages.map((m, idx) => (
            <div key={idx} className={`message-bubble ${m.role} animate-fade-in`}>
              <div className="bubble-sender">
                {m.role === 'user' ? 'Passenger' : 'AI Assistant'}
              </div>
              <div className="bubble-content">
                {renderMarkdown(m.content)}
                
                {/* Boarding pass style ticket rendering */}
                {m.role === 'assistant' && m.raw_data && m.raw_data.pnr_data && (
                  <div className="ticket-boarding-pass">
                    <div className="ticket-header">
                      <span>BOARDING TICKET</span>
                      <span className="pnr-title">PNR: {m.raw_data.pnr_data.pnr}</span>
                    </div>
                    <div className="ticket-body">
                      <div className="route-row">
                        <div className="station">
                          <h3>{m.raw_data.pnr_data.from_code}</h3>
                          <p>{m.raw_data.pnr_data.from_station}</p>
                        </div>
                        <div className="train-icon-col">
                          <span>{m.raw_data.pnr_data.train_no}</span>
                          <span className="train-name-sub">{m.raw_data.pnr_data.train_name}</span>
                        </div>
                        <div className="station text-right">
                          <h3>{m.raw_data.pnr_data.to_code}</h3>
                          <p>{m.raw_data.pnr_data.to_station}</p>
                        </div>
                      </div>
                      <div className="ticket-details">
                        <div>
                          <span className="lbl">Passenger</span>
                          <span className="val">{m.raw_data.pnr_data.passenger_name} ({m.raw_data.pnr_data.passenger_age} yrs)</span>
                        </div>
                        <div>
                          <span className="lbl">Travel Date</span>
                          <span className="val">{m.raw_data.pnr_data.travel_date}</span>
                        </div>
                        <div>
                          <span className="lbl">Class</span>
                          <span className="val">{m.raw_data.pnr_data.travel_class}</span>
                        </div>
                        <div>
                          <span className="lbl">Status</span>
                          <span className={`val ${m.raw_data.pnr_data.booking_status === 'CNF' ? 'cnf-text' : 'wl-text'}`}>{m.raw_data.pnr_data.booking_status}</span>
                        </div>
                      </div>
                      {m.raw_data.pnr_data.booking_status === 'CNF' && (
                        <div className="berth-assignment">
                          Coach: <strong>{m.raw_data.pnr_data.coach}</strong> | Seat: <strong>{m.raw_data.pnr_data.seat_no}</strong>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Live Train Status Card */}
                {m.role === 'assistant' && m.raw_data && (
                  m.raw_data.current_station && !m.raw_data.pnr_data
                ) && (
                  <div className="ticket-boarding-pass animate-fade-in">
                    <div className="ticket-header">
                      <span>LIVE TRAIN STATUS</span>
                      <span className="pnr-title">{m.raw_data.train_no || 'Train'}</span>
                    </div>
                    <div className="ticket-body">
                      <div className="ticket-details">
                        <div>
                          <span className="lbl">Current</span>
                          <span className="val">{m.raw_data.current_station || 'Unknown'}</span>
                        </div>
                        <div>
                          <span className="lbl">Next</span>
                          <span className="val">{m.raw_data.next_station || 'Unknown'}</span>
                        </div>
                        <div>
                          <span className="lbl">Delay</span>
                          <span className="val">{m.raw_data.delay_mins || 0} min</span>
                        </div>
                        <div>
                          <span className="lbl">ETA</span>
                          <span className="val">{m.raw_data.eta || 'N/A'}</span>
                        </div>
                      </div>
                      <div className="berth-assignment">
                        Status: <strong>{m.raw_data.status || 'Live status available'}</strong>
                      </div>
                    </div>
                  </div>
                )}

                {/* SVG Route Timelines for Schedules */}
                {m.role === 'assistant' && m.raw_data && m.raw_data.stops && renderRouteTimeline(m.raw_data)}
              </div>
            </div>
          ))}

          {loading && (
            <div className="message-bubble assistant animate-fade-in">
              <div className="bubble-sender">AI Assistant</div>
              <div className="bubble-content loading-shimmer">
                <div className="shimmer-line"></div>
                <div className="shimmer-line short"></div>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Input Bar */}
        <div className="input-bar">
          <button 
            className={`voice-mic-btn ${isListening ? 'listening' : ''}`}
            onClick={isListening ? stopSpeechRecognition : startSpeechRecognition}
            title="Voice input in Hindi/English"
          >
            {isListening ? <MicOff size={20} /> : <Mic size={20} />}
          </button>
          <input 
            type="text" 
            placeholder={isListening ? "Listening..." : "Ask about trains, PNR, seat availability..."}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
            disabled={loading}
          />
          <button 
            className="send-btn" 
            onClick={() => sendMessage()}
            disabled={loading || !input.trim()}
          >
            <Send size={18} />
          </button>
        </div>
      </main>

      {/* ── RIGHT PANEL: Agent reasoning logs & RAG Inspector ── */}
      <aside className="right-panel">
        <div className="right-header">
          <Sparkles className="header-icon" />
          <h3>Agent Logs & RAG Scores</h3>
        </div>

        {/* Live Reasoning Logs */}
        <div className="right-section">
          <div className="section-title">
            <Eye size={16} />
            <h3>Execution Trace</h3>
          </div>
          
          {activeTrace.length === 0 ? (
            <div className="empty-state">
              <p>Send a query to view agent reasoning logs and tool invocations step-by-step.</p>
            </div>
          ) : (
            <div className="trace-logs scroll-container">
              {activeTrace.map((log, idx) => (
                <div key={idx} className="trace-item animate-fade-in">
                  <div className="trace-index">{idx + 1}</div>
                  <p className="trace-text">{log}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* RAG Source Inspector */}
        <div className="right-section">
          <div className="section-title">
            <Info size={16} />
            <h3>RAG Hybrid Retrieval Info</h3>
          </div>

          {activeSources.length === 0 ? (
            <div className="empty-state">
              <p>Sources matching policy queries (refunds, concessions, Tatkal) will be displayed here.</p>
            </div>
          ) : (
            <div className="sources-list scroll-container">
              {activeSources.map((src, idx) => (
                <div key={idx} className="source-card animate-fade-in">
                  <div className="source-meta">
                    <span className="source-name">{src.source || src.name || `Source ${idx + 1}`}</span>
                    <span className="source-chunk">Chunk {src.chunk_index ?? idx + 1}</span>
                  </div>
                  <p className="source-text">"{src.text || src.document || src.content || src}"</p>
                  <div className="score-row">
                    <div className="score-badge">
                      Chroma Score: <strong>{Number(src.chroma_score ?? src.qdrant_score ?? src.score ?? 0).toFixed(4)}</strong>
                    </div>
                    <div className="score-badge rerank">
                      FlashRank Rerank: <strong>{Number(src.rerank_score ?? 0).toFixed(4)}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
