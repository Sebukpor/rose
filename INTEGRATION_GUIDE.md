# ROSE Clinical Triage Engine - Integration Guide

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Authentication & Authorization](#authentication--authorization)
4. [Payment Gateway & Token Usage Tracking](#payment-gateway--token-usage-tracking)
5. [API Endpoints](#api-endpoints)
6. [Frontend Integration Examples](#frontend-integration-examples)
7. [Environment Configuration](#environment-configuration)
8. [Error Handling](#error-handling)
9. [Best Practices](#best-practices)

---

## 🏥 Overview

**ROSE** (Clinical Triage Engine) is a production-grade backend system for clinical triage with integrated payment gateway, token-based usage tracking, and freemium tier management. This guide helps frontend developers and mobile app developers integrate successfully with the platform.

### Key Features

- **JWT Authentication**: Secure user authentication with access/refresh tokens
- **Token-Based Billing**: Track API usage per user with monthly quotas
- **Freemium Tiers**: Free, Plus, Pro, Enterprise, and Admin tiers
- **Context Caching**: Gemini context caching for cost optimization
- **Multi-Modal Input**: Text, audio, and image processing
- **Clinical Safety**: Built-in safety protocols and audit logging

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Frontend App  │────▶│   ROSE Backend   │────▶│  Supabase DB    │
│   (Web/Mobile)  │◀────│   (FastAPI)      │◀────│  (PostgreSQL)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │  Google Gemini   │
                        │  (LLM + Cache)   │
                        └──────────────────┘
```

### Technology Stack

- **Backend Framework**: FastAPI 0.111.0
- **Database**: Supabase PostgreSQL (via SQLAlchemy ORM)
- **Authentication**: JWT (HS256 algorithm)
- **Password Hashing**: bcrypt
- **AI/ML**: Google Gemini API, Whisper STT, Piper TTS
- **Translation**: Argos Translate (14 languages including Hindi)

---

## 🔐 Authentication & Authorization

### Authentication Flow

1. **User Registration** → Receive access token + refresh token
2. **User Login** → Receive access token + refresh token
3. **API Calls** → Include access token in `Authorization: Bearer <token>` header
4. **Token Refresh** → Use refresh token to get new access token

### Token Structure

**Access Token Payload:**
```json
{
  "user_id": "uuid-string",
  "email": "user@example.com",
  "tier": "free",
  "iat": 1234567890,
  "exp": 1234567890,
  "type": "access"
}
```

**Refresh Token Payload:**
```json
{
  "user_id": "uuid-string",
  "iat": 1234567890,
  "exp": 1234567890,
  "type": "refresh"
}
```

### Token Expiration

| Token Type | Expiration |
|------------|------------|
| Access Token | 30 days (configurable via `JWT_EXPIRATION_DAYS`) |
| Refresh Token | 90 days (configurable via `JWT_REFRESH_EXPIRATION_DAYS`) |

---

## 💳 Payment Gateway & Token Usage Tracking

### Freemium Tiers

| Tier | Monthly Token Limit | Price/Month | Use Case |
|------|---------------------|-------------|----------|
| **FREE** | 10,000 tokens | $0.00 | Individual use, ~10 sessions/month |
| **PLUS** | 50,000 tokens | $14.99 | Small clinic, ~50 sessions/month |
| **PRO** | 100,000 tokens | $29.99 | Medium clinic, ~200 sessions/month |
| **ENTERPRISE** | Unlimited | $999.99 | Hospital systems, unlimited |
| **ADMIN** | Unlimited | $0.00 | Internal testing |

### How Token Tracking Works

1. **Before Each Request**: System checks if user has sufficient quota
2. **During Processing**: Token usage is estimated (~2000 tokens per triage call)
3. **After Completion**: Actual token usage is recorded (input + output - cached)
4. **Billing Cycle**: Resets on calendar month (1st of each month)

### Token Calculation

```
Total Billable Tokens = Input Tokens + Output Tokens - Cached Tokens
```

**Example:**
- Input: 500 tokens
- Output: 1500 tokens
- Cached: 200 tokens (from context cache)
- **Billable**: 500 + 1500 - 200 = **1800 tokens**

### Quota Enforcement

When a user exceeds their monthly limit:
- HTTP 429 status code returned
- Error message includes current usage, limit, and days remaining
- User must upgrade tier or wait for next billing cycle

---

## 🌐 API Endpoints

### Base URL

```
Production: https://your-domain.com
Local Development: http://localhost:7860
```

### Authentication Endpoints

#### 1. Register User

**POST** `/api/v1/auth/register`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "tier": "free"
}
```

**Response (201 Created):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 2592000,
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "tier": "free"
}
```

#### 2. Login

**POST** `/api/v1/auth/login`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 2592000,
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "tier": "free"
}
```

#### 3. Refresh Token

**POST** `/api/v1/auth/refresh`

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 2592000
}
```

#### 4. Get User Profile

**GET** `/api/v1/auth/me`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "tier": "free",
  "monthly_token_limit": 10000,
  "is_active": true,
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

### Usage Tracking Endpoints

#### 5. Get Quota Status

**GET** `/api/v1/usage/status`

**Headers:**
```
User-Id: 550e8400-e29b-41d4-a716-446655440000
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "data": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "tier": "free",
    "monthly_limit": 10000,
    "current_usage": 3500,
    "remaining": 6500,
    "percentage_used": 35.0,
    "billing_cycle_start": "2024-04-01T00:00:00Z",
    "billing_cycle_end": "2024-04-30T23:59:59Z",
    "days_remaining": 15,
    "price_per_month": 0.0,
    "unlimited": false
  }
}
```

#### 6. Get Usage History

**GET** `/api/v1/usage/history?days=30`

**Headers:**
```
User-Id: 550e8400-e29b-41d4-a716-446655440000
Authorization: Bearer <access_token>
```

**Query Parameters:**
- `days`: Number of days (1-365, default: 30)

**Response (200 OK):**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "period_days": 30,
  "total_tokens": 3500,
  "total_requests": 15,
  "requests_by_endpoint": {
    "/interact": {"requests": 12, "tokens": 3000},
    "/interact/stream": {"requests": 3, "tokens": 500}
  },
  "requests_by_date": {
    "2024-04-01": {"requests": 2, "tokens": 400},
    "2024-04-02": {"requests": 1, "tokens": 200}
  },
  "records": [
    {
      "id": 1,
      "user_id": "550e8400-e29b-41d4-a716-446655440000",
      "session_id": "session-123",
      "endpoint": "/interact",
      "input_tokens": 500,
      "output_tokens": 1500,
      "cached_tokens": 200,
      "total_billable_tokens": 1800,
      "timestamp": "2024-04-01T10:30:00Z",
      "cache_hit": false,
      "error": null
    }
  ]
}
```

#### 7. Get Pricing Tiers

**GET** `/api/v1/pricing/tiers`

**Query Parameters:**
- `tier`: Optional specific tier (free, plus, pro, enterprise)

**Response (200 OK):**
```json
{
  "tiers": {
    "free": {
      "name": "Free",
      "price": "$0.00/month",
      "limit": "10,000 tokens/month",
      "use_cases": ["Individual use", "Testing & evaluation", "~10 patient sessions/month"]
    },
    "plus": {
      "name": "Plus",
      "price": "$14.99/month",
      "limit": "50,000 tokens/month",
      "use_cases": ["Small clinic operations", "~50 patient sessions/month", "Priority support"]
    },
    "pro": {
      "name": "Pro",
      "price": "$29.99/month",
      "limit": "100,000 tokens/month",
      "use_cases": ["Medium clinic operations", "~200 patient sessions/month", "API access", "Custom integrations"]
    },
    "enterprise": {
      "name": "Enterprise",
      "price": "$999.99/month",
      "limit": "Unlimited",
      "use_cases": ["Hospital systems", "Unlimited usage", "Dedicated support", "SLA guarantees"]
    }
  }
}
```

---

### Clinical Triage Endpoints

#### 8. Interact (Primary Triage Endpoint)

**POST** `/api/v1/avatar/interact`

**Headers:**
```
Authorization: Bearer <access_token>
Session-Id: session-123 (optional, auto-generated if not provided)
Content-Type: application/json
```

**Request:**
```json
{
  "current_input_text": "I have a headache and fever",
  "current_input_image": null,
  "current_input_audio": null,
  "conversation_history": [
    {
      "role": "patient",
      "content": "Hello, I'm not feeling well"
    },
    {
      "role": "assistant",
      "content": "I'm sorry to hear that. Can you describe your symptoms?"
    }
  ],
  "language": "en",
  "include_audio_response": true,
  "include_clinical_summary": true
}
```

**Response (200 OK):**
```json
{
  "patient_response": {
    "text": "Thank you for sharing. A headache and fever could indicate several conditions...",
    "audio": "base64_encoded_audio_data",
    "emotion": {
      "label": "empathetic",
      "intensity": 0.8
    }
  },
  "care_routing": {
    "recommended_pathway": "primary_care",
    "urgency_level": "moderate"
  },
  "clinical_summary": {
    "available": true,
    "summary_text": "Patient reports headache and fever. Onset 2 days ago...",
    "generated_at": "2024-04-14T10:30:00Z"
  },
  "session_id": "session-123",
  "request_id": "req-456",
  "timing": {
    "stt_ms": 0,
    "translation_ms": 0,
    "llm_ms": 1500,
    "tts_ms": 800,
    "total_ms": 2300
  },
  "token_usage": {
    "input_tokens": 500,
    "output_tokens": 1500,
    "cached_tokens": 200,
    "total_tokens": 1800
  }
}
```

**Error Response (429 Too Many Requests):**
```json
{
  "error": "quota_exceeded",
  "message": "Monthly token limit exceeded: 10500/10000 tokens used. Current tier: free. Days remaining: 15.",
  "suggestion": "Upgrade to Plus tier for 50,000 tokens/month at /api/v1/pricing/tiers"
}
```

#### 9. Interact Stream (Real-time Streaming)

**POST** `/api/v1/avatar/interact/stream`

Similar to `/interact` but returns Server-Sent Events (SSE) for real-time streaming responses.

---

## 💻 Frontend Integration Examples

### JavaScript/TypeScript Example

```typescript
// api-client.ts
class ROSEApiClient {
  private baseURL: string;
  private accessToken: string | null = null;
  private refreshToken: string | null = null;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  // Set tokens after login/register
  setTokens(access: string, refresh: string) {
    this.accessToken = access;
    this.refreshToken = refresh;
  }

  // Private method for authenticated requests
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.accessToken}`,
        ...options.headers,
      },
    });

    if (response.status === 401) {
      // Token expired, try to refresh
      await this.refreshAccessToken();
      // Retry original request
      return this.request<T>(endpoint, options);
    }

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Request failed');
    }

    return response.json();
  }

  // Register new user
  async register(email: string, password: string, tier: string = 'free') {
    const data = await this.request('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, tier }),
    });
    
    this.setTokens(data.access_token, data.refresh_token);
    return data;
  }

  // Login
  async login(email: string, password: string) {
    const data = await this.request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    
    this.setTokens(data.access_token, data.refresh_token);
    return data;
  }

  // Refresh access token
  async refreshAccessToken() {
    const data = await fetch(`${this.baseURL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: this.refreshToken }),
    }).then(r => r.json());

    this.setTokens(data.access_token, this.refreshToken);
    return data;
  }

  // Get quota status
  async getQuotaStatus(userId: string) {
    return this.request('/api/v1/usage/status', {
      headers: { 'User-Id': userId },
    });
  }

  // Send triage request
  async sendTriageRequest(
    text: string,
    sessionId: string,
    conversationHistory: Array<{role: string, content: string}> = []
  ) {
    return this.request('/api/v1/avatar/interact', {
      method: 'POST',
      headers: { 'Session-Id': sessionId },
      body: JSON.stringify({
        current_input_text: text,
        conversation_history: conversationHistory,
        language: 'en',
        include_audio_response: false,
      }),
    });
  }
}

// Usage Example
const api = new ROSEApiClient('https://your-domain.com');

// Register
try {
  const user = await api.register('user@example.com', 'password123');
  console.log('Registered:', user.email);
} catch (error) {
  console.error('Registration failed:', error.message);
}

// Check quota before making request
const quota = await api.getQuotaStatus(user.user_id);
console.log(`Remaining tokens: ${quota.data.remaining}`);

// Send triage request
try {
  const response = await api.sendTriageRequest(
    'I have a headache',
    'session-123',
    []
  );
  console.log('Response:', response.patient_response.text);
} catch (error) {
  if (error.message.includes('quota exceeded')) {
    console.log('Please upgrade your plan');
  }
}
```

### React Hook Example

```tsx
// hooks/useROSE.ts
import { useState, useCallback } from 'react';

interface User {
  user_id: string;
  email: string;
  tier: string;
}

interface QuotaStatus {
  data: {
    monthly_limit: number;
    current_usage: number;
    remaining: number;
    percentage_used: number;
    days_remaining: number;
  };
}

export function useROSE(baseURL: string) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const login = useCallback(async (email: string, password: string) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${baseURL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail);
      }

      const data = await response.json();
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      setUser({ user_id: data.user_id, email: data.email, tier: data.tier });
      
      return data;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [baseURL]);

  const checkQuota = useCallback(async () => {
    if (!user || !accessToken) return null;

    try {
      const response = await fetch(`${baseURL}/api/v1/usage/status`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'User-Id': user.user_id,
        },
      });

      const data = await response.json();
      return data as QuotaStatus;
    } catch (err) {
      console.error('Failed to check quota:', err);
      return null;
    }
  }, [user, accessToken, baseURL]);

  const sendTriageRequest = useCallback(async (
    text: string,
    sessionId: string,
    history: Array<{role: string, content: string}> = []
  ) => {
    if (!accessToken) throw new Error('Not authenticated');

    // Check quota first
    const quota = await checkQuota();
    if (quota && quota.data.remaining <= 0) {
      throw new Error('Quota exceeded. Please upgrade your plan.');
    }

    const response = await fetch(`${baseURL}/api/v1/avatar/interact`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'Session-Id': sessionId,
      },
      body: JSON.stringify({
        current_input_text: text,
        conversation_history: history,
        language: 'en',
      }),
    });

    if (response.status === 429) {
      const errorData = await response.json();
      throw new Error(errorData.detail);
    }

    return response.json();
  }, [accessToken, baseURL, checkQuota]);

  return {
    user,
    isAuthenticated: !!accessToken,
    loading,
    error,
    login,
    checkQuota,
    sendTriageRequest,
  };
}

// Usage in Component
function TriageComponent() {
  const { login, checkQuota, sendTriageRequest, isAuthenticated } = useROSE('https://your-domain.com');
  const [input, setInput] = useState('');
  const [sessionId] = useState(() => `session-${Date.now()}`);

  const handleSubmit = async () => {
    try {
      // Check quota before sending
      const quota = await checkQuota();
      console.log(`Using ${quota.data.remaining} tokens remaining`);

      const response = await sendTriageRequest(input, sessionId);
      console.log(response.patient_response.text);
    } catch (error) {
      alert(error.message);
    }
  };

  return (
    <div>
      {!isAuthenticated ? (
        <button onClick={() => login('user@example.com', 'password')}>
          Login
        </button>
      ) : (
        <div>
          <textarea value={input} onChange={e => setInput(e.target.value)} />
          <button onClick={handleSubmit}>Send</button>
        </div>
      )}
    </div>
  );
}
```

### Mobile App Example (React Native)

```tsx
// services/rose-api.ts
import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEYS = {
  ACCESS_TOKEN: '@rose_access_token',
  REFRESH_TOKEN: '@rose_refresh_token',
  USER_ID: '@rose_user_id',
};

class ROSEService {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  async login(email: string, password: string) {
    const response = await fetch(`${this.baseURL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
      throw new Error('Login failed');
    }

    const data = await response.json();
    
    // Store tokens securely
    await AsyncStorage.multiSet([
      [STORAGE_KEYS.ACCESS_TOKEN, data.access_token],
      [STORAGE_KEYS.REFRESH_TOKEN, data.refresh_token],
      [STORAGE_KEYS.USER_ID, data.user_id],
    ]);

    return data;
  }

  async getToken(): Promise<string | null> {
    return AsyncStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
  }

  async getUserId(): Promise<string | null> {
    return AsyncStorage.getItem(STORAGE_KEYS.USER_ID);
  }

  async checkQuota(): Promise<any> {
    const token = await this.getToken();
    const userId = await this.getUserId();

    if (!token || !userId) {
      throw new Error('Not authenticated');
    }

    const response = await fetch(`${this.baseURL}/api/v1/usage/status`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'User-Id': userId,
      },
    });

    return response.json();
  }

  async sendTriage(text: string, sessionId: string) {
    const token = await this.getToken();

    if (!token) {
      throw new Error('Not authenticated');
    }

    // Check quota first
    const quota = await this.checkQuota();
    if (quota.data.remaining <= 0) {
      throw new Error(
        `Quota exceeded. ${quota.data.current_usage}/${quota.data.monthly_limit} tokens used.`
      );
    }

    const response = await fetch(`${this.baseURL}/api/v1/avatar/interact`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'Session-Id': sessionId,
      },
      body: JSON.stringify({
        current_input_text: text,
        conversation_history: [],
        language: 'en',
      }),
    });

    if (response.status === 429) {
      const error = await response.json();
      throw new Error(error.detail);
    }

    return response.json();
  }
}

export const roseAPI = new ROSEService('https://your-domain.com');
```

---

## ⚙️ Environment Configuration

### Required Environment Variables

Create a `.env` file or set these environment variables:

```bash
# Server Configuration
ENVIRONMENT=production
PORT=7860
CORS_ORIGINS=https://your-frontend.com,https://www.your-frontend.com

# Database (Supabase PostgreSQL)
DATABASE_URL=postgresql://user:password@host:5432/database

# JWT Authentication
JWT_SECRET_KEY=your-super-secret-key-min-32-chars-long
JWT_ALGORITHM=HS256
JWT_EXPIRATION_DAYS=30
JWT_REFRESH_EXPIRATION_DAYS=90

# Google Gemini API
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
GEMINI_CACHE_ENABLED=true
GEMINI_CACHE_TTL_MINUTES=60
GEMINI_CACHE_MIN_TOKENS=4096

# Token Tracking & Billing
TOKEN_TRACKING_ENABLED=true
USAGE_DB_PATH=/tmp/usage_tracking.db
DEFAULT_FREE_TIER_LIMIT=10000
DEFAULT_PLUS_TIER_LIMIT=50000
DEFAULT_PRO_TIER_LIMIT=100000
BILLING_CYCLE_TYPE=calendar_month

# Speech-to-Text (Whisper)
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=auto
MAX_AUDIO_DURATION_SECONDS=60

# Text-to-Speech (Piper)
PIPER_VOICE_EN=en_US-amy-medium
PIPER_VOICE_HI=hi_IN-priyamvada-medium

# Translation
ARGOS_SUPPORTED_LANGUAGES=en,es,fr,de,it,pt,zh,ja,ko,ar,hi,sw,ru

# CORS & Security
CORS_ORIGINS=*
PROMPT_INJECTION_THRESHOLD=0.7
```

### Docker Deployment

```bash
# Build Docker image
docker build -t rose-backend .

# Run container
docker run -d \
  --name rose-backend \
  -p 7860:7860 \
  --env-file .env \
  rose-backend
```

---

## ❌ Error Handling

### Common Error Codes

| Status Code | Error Type | Description | Action |
|-------------|-----------|-------------|--------|
| 400 | Bad Request | Invalid input format | Check request schema |
| 401 | Unauthorized | Missing or invalid token | Re-authenticate user |
| 403 | Forbidden | Inactive account or insufficient permissions | Contact support |
| 413 | Payload Too Large | Audio file exceeds 5MB limit | Compress or split audio |
| 429 | Too Many Requests | Monthly token quota exceeded | Upgrade tier or wait for reset |
| 500 | Internal Server Error | Server-side error | Retry with exponential backoff |
| 503 | Service Unavailable | Usage tracking unavailable | Check service health |

### Error Response Format

```json
{
  "error": "error_type",
  "message": "Human-readable error message",
  "suggestion": "Recommended action to resolve"
}
```

### Retry Strategy

```typescript
async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  maxRetries: number = 3,
  baseDelay: number = 1000
): Promise<T> {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      
      // Only retry on 5xx errors
      if (error.status >= 500) {
        const delay = baseDelay * Math.pow(2, i);
        await new Promise(resolve => setTimeout(resolve, delay));
      } else {
        throw error;
      }
    }
  }
}
```

---

## ✅ Best Practices

### 1. Token Management

- **Store tokens securely**: Use secure storage (Keychain, Keystore, encrypted AsyncStorage)
- **Refresh before expiry**: Refresh tokens when they're 80% through their lifetime
- **Handle 401 errors**: Automatically refresh and retry on authentication failures

### 2. Quota Monitoring

- **Check before sending**: Always check quota before making expensive API calls
- **Show usage to users**: Display remaining tokens and upgrade options in UI
- **Warn at thresholds**: Alert users at 80% and 95% quota usage

### 3. Session Management

- **Generate unique session IDs**: Use UUIDs for session tracking
- **Maintain conversation context**: Send conversation history for coherent interactions
- **Limit history length**: Keep conversation history under MAX_CONVERSATION_TURNS (15)

### 4. Error Handling

- **Graceful degradation**: Show friendly messages instead of raw errors
- **Retry logic**: Implement exponential backoff for transient failures
- **Log errors**: Track errors for debugging and monitoring

### 5. Performance Optimization

- **Use streaming**: For long responses, use `/interact/stream` endpoint
- **Enable caching**: Context caching reduces token usage by 10-30%
- **Compress audio**: Keep audio files under 5MB and 60 seconds

### 6. Security

- **HTTPS only**: Never send tokens over unencrypted connections
- **Validate input**: Sanitize all user inputs before sending
- **Rate limiting**: Implement client-side rate limiting to prevent abuse

---

## 📞 Support & Resources

- **API Documentation**: `https://your-domain.com/docs` (Swagger UI)
- **Alternative Docs**: `https://your-domain.com/redoc` (ReDoc)
- **Health Check**: `GET https://your-domain.com/health`

### Contact

For integration support, contact the development team with:
- Your use case and expected traffic
- Current tier and usage patterns
- Specific integration challenges

---

## 📝 Changelog

### Version 1.0 (Current)

- ✅ JWT authentication with refresh tokens
- ✅ Token-based usage tracking
- ✅ Freemium tier system (Free, Plus, Pro, Enterprise)
- ✅ Gemini context caching
- ✅ Multi-modal input (text, audio, image)
- ✅ 14-language translation support
- ✅ Clinical safety protocols
- ✅ Comprehensive audit logging

---

**Last Updated**: April 2024  
**Version**: 1.0  
**Maintained By**: ROSE Development Team
