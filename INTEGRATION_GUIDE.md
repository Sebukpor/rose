# ROSE Clinical Triage Engine - Integration Guide

> **Live API Documentation**: https://sebukpor-rose-triage-backend.hf.space/docs#/
> 
> **Version**: 1.0 | **Last Updated**: April 2025

## 📋 Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Authentication & Authorization](#authentication--authorization)
4. [Payment Gateway & Token Usage Tracking](#payment-gateway--token-usage-tracking)
5. [API Endpoints Reference](#api-endpoints-reference)
6. [Frontend Integration Examples](#frontend-integration-examples)
7. [Mobile App Integration (React Native/Flutter)](#mobile-app-integration)
8. [Environment Configuration](#environment-configuration)
9. [Error Handling & Status Codes](#error-handling--status-codes)
10. [Best Practices & Checklist](#best-practices--checklist)
11. [Known Limitations & Improvements](#known-limitations--improvements)

---

## 🏥 Overview

**ROSE** (Clinical Triage Engine) is a production-grade backend system for clinical triage with integrated payment gateway, token-based usage tracking, and freemium tier management. This guide helps frontend developers and mobile app developers integrate successfully with the platform.

### Key Features

- **JWT Authentication**: Secure user authentication with access/refresh tokens
- **Token-Based Billing**: Track API usage per user with monthly quotas
- **Freemium Tiers**: Free, Plus, Pro, Enterprise, and Admin tiers
- **Context Caching**: Gemini context caching for cost optimization (reduces billable tokens)
- **Multi-Modal Input**: Text, audio (base64), and image (base64) processing
- **Real-time Streaming**: Server-Sent Events (SSE) for streaming responses
- **Clinical Safety**: Built-in safety protocols and audit logging
- **Multi-language Support**: 14 languages including Hindi, Swahili, French, Spanish

### Important Notes for Integrators

⚠️ **Critical Integration Points:**

1. **Token Usage is Returned in Every Response**: The `token_usage` field in `/interact` responses shows exact billable tokens
2. **Quota Checked Before Processing**: Requests are rejected with HTTP 429 if quota exceeded
3. **Session Management**: Use `Session-Id` header to maintain conversation context
4. **Image Consent Required**: Set `image_consent_acknowledged: true` when sending images
5. **Audio Constraints**: Max file size enforced (HTTP 413 if exceeded)

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
                        │      Rose   │
                        │  (LLM + Cache)   │
                        └──────────────────┘
```

### Technology Stack

| Component | Technology |
|-----------|------------|
| Backend Framework | FastAPI 0.111.0 |
| Database | Supabase PostgreSQL (via SQLAlchemy ORM) |
| Authentication | JWT (HS256 algorithm) |
| Password Hashing | bcrypt |
| AI/ML | Rose, Whisper STT, Piper TTS |
| Translation | Argos Translate (14 languages) |
| API Documentation | Swagger UI (OpenAPI 3.1.0) |

---

## 🔐 Authentication & Authorization

### Authentication Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant ROSE API
    
    User->>Frontend: Enter credentials
    Frontend->>ROSE API: POST /api/v1/auth/register or /login
    ROSE API-->>Frontend: access_token + refresh_token
    Frontend->>Frontend: Store tokens securely
    
    loop Every API Call
        Frontend->>ROSE API: Authorization: Bearer {access_token}
        alt Token Expired
            ROSE API-->>Frontend: 401 Unauthorized
            Frontend->>ROSE API: POST /api/v1/auth/refresh
            ROSE API-->>Frontend: New access_token
            Frontend->>ROSE API: Retry with new token
        end
    end
```

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

| Token Type | Default Expiration | Environment Variable |
|------------|-------------------|----------------------|
| Access Token | 30 days | `JWT_EXPIRATION_DAYS` |
| Refresh Token | 90 days | `JWT_REFRESH_EXPIRATION_DAYS` |

### Security Best Practices

1. **Store tokens securely**: Use HttpOnly cookies or secure storage (Keychain/Keystore)
2. **Never expose tokens in client-side code**: Keep tokens out of localStorage in production
3. **Implement token rotation**: Refresh tokens before expiration
4. **Use HTTPS only**: All API calls must be over HTTPS in production

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

> 💡 **Get Current Pricing**: `GET /api/v1/pricing/tiers` returns up-to-date tier information

### How Token Tracking Works

1. **Before Each Request**: System checks if user has sufficient quota
2. **During Processing**: Token usage is estimated (~2000 tokens per triage call average)
3. **After Completion**: Actual token usage is recorded and returned in response
4. **Billing Cycle**: Resets on calendar month (1st of each month)

### Token Calculation Formula

```
Total Billable Tokens = Input Tokens + Output Tokens - Cached Tokens
```

**Example Calculation:**
```
Input tokens:     500
Output tokens:   1500
Cached tokens:   -200  (from Gemini context cache)
─────────────────────
Billable:        1800 tokens
```

### Quota Enforcement

When a user exceeds their monthly limit:

- **HTTP Status**: 429 Too Many Requests
- **Response Body**:
```json
{
  "error": "quota_exceeded",
  "message": "Monthly token limit exceeded: 10500/10000 tokens used. Current tier: free. Days remaining: 15.",
  "suggestion": "Upgrade to Plus tier for 50,000 tokens/month"
}
```

### Monitoring Usage

Frontend should implement:

1. **Pre-flight Check**: Call `/api/v1/usage/status` before expensive operations
2. **Progressive Warnings**: Show warnings at 80%, 90%, 95% usage
3. **Upgrade Prompts**: Display tier upgrade options when approaching limits
4. **Usage Dashboard**: Show daily/weekly breakdown from `/api/v1/usage/history`

---

## 🌐 API Endpoints Reference

### Base URLs

| Environment | URL |
|-------------|-----|
| Production | `https://sebukpor-rose-triage-backend.hf.space` |
| Local Development | `http://localhost:7860` |

### Complete Endpoint List

| Method | Endpoint | Auth Required | Description |
|--------|----------|---------------|-------------|
| GET | `/health` | ❌ | Health check (liveness/readiness) |
| POST | `/api/v1/auth/register` | ❌ | Register new user |
| POST | `/api/v1/auth/login` | ❌ | User login |
| POST | `/api/v1/auth/refresh` | ❌ | Refresh access token |
| GET | `/api/v1/auth/me` | ✅ | Get current user profile |
| POST | `/api/v1/avatar/interact` | ✅ | Primary triage interaction |
| POST | `/api/v1/avatar/interact/stream` | ✅ | Streaming triage (SSE) |
| GET | `/api/v1/avatar/cache/stats` | ✅ | Context cache statistics |
| GET | `/api/v1/usage/status` | ✅ | Get quota status |
| GET | `/api/v1/usage/history` | ✅ | Get usage history |
| GET | `/api/v1/pricing/tiers` | ❌ | Get pricing tier info |

---

### Authentication Endpoints

#### 1. Register User

**POST** `/api/v1/auth/register`

**Request Schema:**
```json
{
  "email": "user@example.com",
  "password": "securepassword123",
  "tier": "free"  // Optional, default: "free"
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

**Error Responses:**
- `400 Bad Request`: Email already exists or invalid tier
- `422 Validation Error`: Invalid email format or weak password

---

#### 2. Login

**POST** `/api/v1/auth/login`

**Request Schema:**
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

**Error Responses:**
- `401 Unauthorized`: Invalid credentials
- `422 Validation Error`: Invalid email format

---

#### 3. Refresh Token

**POST** `/api/v1/auth/refresh`

**Request Schema:**
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

**Error Responses:**
- `401 Unauthorized`: Invalid or expired refresh token
- `422 Validation Error`: Missing refresh_token field

---

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

**Error Responses:**
- `401 Unauthorized`: Invalid or missing access token

---

### Usage Tracking Endpoints

#### 5. Get Quota Status

**GET** `/api/v1/usage/status`

**Headers:**
```
Authorization: Bearer <access_token>
User-Id: 550e8400-e29b-41d4-a716-446655440000
```

> ⚠️ **Important**: The `User-Id` header is currently required. This should match the authenticated user's ID from the JWT token.

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

---

#### 6. Get Usage History

**GET** `/api/v1/usage/history?days=30`

**Headers:**
```
Authorization: Bearer <access_token>
User-Id: 550e8400-e29b-41d4-a716-446655440000
```

**Query Parameters:**
| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `days` | integer | 30 | 1-365 | Number of days of history to retrieve |

**Response (200 OK):**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "period_days": 30,
  "total_tokens": 3500,
  "total_requests": 15,
  "requests_by_endpoint": {
    "/api/v1/avatar/interact": {"requests": 12, "tokens": 3000},
    "/api/v1/avatar/interact/stream": {"requests": 3, "tokens": 500}
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
      "endpoint": "/api/v1/avatar/interact",
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

---

#### 7. Get Pricing Tiers

**GET** `/api/v1/pricing/tiers?tier=plus`

**Query Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tier` | string | No | Specific tier (free, plus, pro, enterprise). Returns all tiers if omitted. |

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
      "use_cases": ["Medium clinic operations", "~200 patient sessions/month", "API access"]
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
Session-Id: session-123  (optional, auto-generated if not provided)
Content-Type: application/json
```

**Request Schema:**
```json
{
  "conversation_history": [
    {
      "role": "user",
      "content": "Hello, I'm not feeling well",
      "language": "en",
      "attached_images": null
    },
    {
      "role": "assistant",
      "content": "I'm sorry to hear that. Can you describe your symptoms?",
      "language": "en",
      "attached_images": null
    }
  ],
  "current_input_type": "text",  // text, audio, image, multimodal
  "current_input_text": "I have a headache and fever",
  "current_input_audio": null,   // base64 encoded audio
  "current_input_image": {       // Optional, see ImageInput schema below
    "data": null,                // base64 encoded image
    "mime_type": null,           // image/jpeg, image/png, etc.
    "description": null          // Optional patient description (max 500 chars)
  },
  "current_input_language": "en",  // BCP-47 language code
  "image_consent_acknowledged": false,
  "response_mode": "text"  // text, audio, both
}
```

**ImageInput Schema (when sending images):**
```json
{
  "data": "base64_encoded_image_data",
  "mime_type": "image/jpeg",
  "description": "Photo of skin rash on arm"
}
```

**Audio Format Requirements:**
- Encoding: base64
- Supported MIME types: `audio/wav`, `audio/mpeg`, `audio/ogg`
- Sample rate: 8000-48000 Hz (default: 24000)
- Max file size: Enforced by server (HTTP 413 if exceeded)

**Response (200 OK):**
```json
{
  "patient_response": {
    "text": "Thank you for sharing. A headache and fever could indicate several conditions...",
    "audio": {
      "encoding": "base64",
      "data": "base64_encoded_audio_data",
      "sample_rate": 24000,
      "mime_type": "audio/wav",
      "duration_ms": 5000
    },
    "emotion": {
      "label": "empathetic",  // calm, empathetic, reassuring, attentive, concerned, neutral
      "intensity": 0.8
    }
  },
  "care_routing": {
    "recommended_pathway": "doctor",  // doctor, hospital, pharmacist, home_care
    "urgency_level": "moderate"       // low, moderate, high
  },
  "clinical_summary": {
    "available": true,
    "summary_text": "Patient reports headache and fever. Onset 2 days ago...",
    "generated_at": "2024-04-14T10:30:00Z"
  },
  "timing": {
    "stt_ms": 0,
    "translation_ms": 0,
    "llm_ms": 1500,
    "tts_ms": 800,
    "total_ms": 2300
  },
  "metadata": {},
  "token_usage": {
    "input_tokens": 500,
    "output_tokens": 1500,
    "cached_tokens": 200,
    "total_billable_tokens": 1800
  },
  "timestamp": "2024-04-14T10:30:00Z"
}
```

**Error Responses:**

| Status | Error Type | Description |
|--------|-----------|-------------|
| 400 | `client_error` | Invalid input (missing required fields, invalid format) |
| 413 | `client_error` | Audio file too large |
| 429 | `quota_exceeded` | Monthly token limit exceeded |
| 500 | `clinical_safety` | Clinical safety protocol triggered (emergency detected) |
| 422 | `validation_error` | Schema validation failed |

**429 Response Example:**
```json
{
  "error": "quota_exceeded",
  "message": "Monthly token limit exceeded: 10500/10000 tokens used. Current tier: free. Days remaining: 15.",
  "suggestion": "Upgrade to Plus tier for 50,000 tokens/month",
  "reference_id": "err-12345"
}
```

**500 Clinical Safety Response:**
```json
{
  "error": "clinical_safety",
  "message": "Potential emergency detected. Immediate medical attention required.",
  "suggestion": "Please call emergency services immediately.",
  "reference_id": "err-67890"
}
```

---

#### 9. Interact Stream (Real-time Streaming)

**POST** `/api/v1/avatar/interact/stream`

Same request schema as `/interact`, but returns **Server-Sent Events (SSE)** for real-time token streaming.

**Headers:**
```
Authorization: Bearer <access_token>
Session-Id: session-123
Content-Type: application/json
Accept: text/event-stream
```

**SSE Response Format:**
```
event: token
data: {"token": "Thank"}

event: token
data: {"token": " you"}

event: token
data: {"token": " for"}

event: done
data: {"complete": true, "token_usage": {...}}
```

**Frontend SSE Implementation:**
```javascript
const eventSource = new EventSource('/api/v1/avatar/interact/stream', {
  headers: {
    'Authorization': `Bearer ${accessToken}`,
    'Content-Type': 'application/json'
  }
});

eventSource.addEventListener('token', (event) => {
  const data = JSON.parse(event.data);
  appendToChat(data.token);
});

eventSource.addEventListener('done', (event) => {
  const data = JSON.parse(event.data);
  console.log('Streaming complete:', data.token_usage);
  eventSource.close();
});
```

---

#### 10. Get Cache Statistics

**GET** `/api/v1/avatar/cache/stats`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Description**: Returns statistics about Gemini context cache usage (for monitoring cost optimization).

---

#### 11. Health Check

**GET** `/health`

**No authentication required.**

**Description**: Liveness and readiness probe. Returns 200 OK if service is healthy.

> ℹ️ Note: Deliberately excludes underlying model name from response for security.

---

## 💻 Frontend Integration Examples

### JavaScript/TypeScript API Client

```typescript
// api-client.ts
class ROSEApiClient {
  private baseURL: string;
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private userId: string | null = null;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  // Set tokens after login/register
  setTokens(access: string, refresh: string, userId: string) {
    this.accessToken = access;
    this.refreshToken = refresh;
    this.userId = userId;
    // Persist to secure storage
    localStorage.setItem('rose_access_token', access);
    localStorage.setItem('rose_refresh_token', refresh);
    localStorage.setItem('rose_user_id', userId);
  }

  // Load tokens from storage
  loadFromStorage() {
    this.accessToken = localStorage.getItem('rose_access_token');
    this.refreshToken = localStorage.getItem('rose_refresh_token');
    this.userId = localStorage.getItem('rose_user_id');
  }

  // Clear tokens on logout
  clearTokens() {
    this.accessToken = null;
    this.refreshToken = null;
    this.userId = null;
    localStorage.removeItem('rose_access_token');
    localStorage.removeItem('rose_refresh_token');
    localStorage.removeItem('rose_user_id');
  }

  // Private method for authenticated requests
  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.accessToken}`,
        ...(this.userId && { 'User-Id': this.userId }),
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
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(error.detail || error.message || 'Request failed');
    }

    return response.json();
  }

  // Register new user
  async register(email: string, password: string, tier: string = 'free') {
    const data = await this.request('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, tier }),
    });
    
    this.setTokens(data.access_token, data.refresh_token, data.user_id);
    return data;
  }

  // Login
  async login(email: string, password: string) {
    const data = await this.request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    
    this.setTokens(data.access_token, data.refresh_token, data.user_id);
    return data;
  }

  // Refresh access token
  async refreshAccessToken() {
    const data = await fetch(`${this.baseURL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: this.refreshToken }),
    }).then(r => r.json());

    this.setTokens(data.access_token, this.refreshToken, this.userId);
    return data;
  }

  // Get current user profile
  async getProfile() {
    return this.request('/api/v1/auth/me');
  }

  // Get quota status
  async getQuotaStatus() {
    return this.request('/api/v1/usage/status');
  }

  // Get usage history
  async getUsageHistory(days: number = 30) {
    return this.request(`/api/v1/usage/history?days=${days}`);
  }

  // Get pricing tiers
  async getPricingTiers(tier?: string) {
    const query = tier ? `?tier=${tier}` : '';
    return this.request(`/api/v1/pricing/tiers${query}`);
  }

  // Send triage request
  async sendTriageRequest(params: {
    text?: string;
    audio?: string;
    image?: { data: string; mime_type: string; description?: string };
    sessionId?: string;
    conversationHistory?: Array<{role: string; content: string; language?: string}>;
    language?: string;
    responseMode?: 'text' | 'audio' | 'both';
  }) {
    const {
      text,
      audio,
      image,
      sessionId,
      conversationHistory = [],
      language = 'en',
      responseMode = 'text',
    } = params;

    // Determine input type
    let current_input_type: string;
    if (image && audio) current_input_type = 'multimodal';
    else if (image) current_input_type = 'image';
    else if (audio) current_input_type = 'audio';
    else current_input_type = 'text';

    return this.request('/api/v1/avatar/interact', {
      method: 'POST',
      headers: sessionId ? { 'Session-Id': sessionId } : {},
      body: JSON.stringify({
        conversation_history: conversationHistory,
        current_input_type,
        current_input_text: text || null,
        current_input_audio: audio || null,
        current_input_image: image || null,
        current_input_language: language,
        image_consent_acknowledged: !!image,
        response_mode: responseMode,
      }),
    });
  }

  // Check quota before making expensive request
  async checkQuotaAndRequest(params: Parameters<typeof this.sendTriageRequest>[0]) {
    const quota = await this.getQuotaStatus();
    const estimatedTokens = 2000; // Average per request
    
    if (quota.data.remaining < estimatedTokens) {
      throw new Error(
        `Insufficient quota. Remaining: ${quota.data.remaining}, ` +
        `Estimated: ${estimatedTokens}. Please upgrade your plan.`
      );
    }
    
    return this.sendTriageRequest(params);
  }
}

// Usage Example
const api = new ROSEApiClient('https://sebukpor-rose-triage-backend.hf.space');

// Initialize from storage
api.loadFromStorage();

// Register
try {
  const user = await api.register('user@example.com', 'password123');
  console.log('Registered:', user.email, 'Tier:', user.tier);
} catch (error) {
  console.error('Registration failed:', error.message);
}

// Check quota before making request
try {
  const quota = await api.getQuotaStatus();
  console.log(`Remaining tokens: ${quota.data.remaining}/${quota.data.monthly_limit}`);
  
  if (quota.data.percentage_used > 80) {
    console.warn('Warning: Over 80% of quota used!');
  }
  
  // Send triage request
  const response = await api.checkQuotaAndRequest({
    text: 'I have a headache',
    sessionId: 'session-123',
    conversationHistory: [],
    responseMode: 'text',
  });
  
  console.log('Response:', response.patient_response.text);
  console.log('Tokens used:', response.token_usage.total_billable_tokens);
  
} catch (error) {
  if (error.message.includes('quota')) {
    console.log('Quota exceeded. Showing upgrade prompt...');
    // Show upgrade UI
  } else {
    console.error('Request failed:', error.message);
  }
}
```

---

### React Hook Example

```tsx
// hooks/useROSE.ts
import { useState, useCallback, useEffect } from 'react';

interface User {
  user_id: string;
  email: string;
  tier: string;
  monthly_token_limit: number;
}

interface QuotaStatus {
  data: {
    monthly_limit: number;
    current_usage: number;
    remaining: number;
    percentage_used: number;
    days_remaining: number;
    unlimited: boolean;
  };
}

interface TriageResponse {
  patient_response: {
    text: string;
    audio?: { data: string; duration_ms: number };
    emotion: { label: string; intensity: number };
  };
  care_routing: {
    recommended_pathway: 'doctor' | 'hospital' | 'pharmacist' | 'home_care';
    urgency_level: 'low' | 'moderate' | 'high';
  };
  token_usage: {
    total_billable_tokens: number;
  };
}

export function useROSE(baseURL: string) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<QuotaStatus | null>(null);

  // Load tokens from storage on mount
  useEffect(() => {
    const storedToken = localStorage.getItem('rose_access_token');
    const storedRefresh = localStorage.getItem('rose_refresh_token');
    const storedUser = localStorage.getItem('rose_user');
    
    if (storedToken && storedRefresh && storedUser) {
      setAccessToken(storedToken);
      setRefreshToken(storedRefresh);
      setUser(JSON.parse(storedUser));
    }
  }, []);

  // Fetch quota when user changes
  useEffect(() => {
    if (user && accessToken) {
      fetchQuota();
    }
  }, [user]);

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
        throw new Error(data.detail || 'Login failed');
      }

      const data = await response.json();
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      
      const userData: User = {
        user_id: data.user_id,
        email: data.email,
        tier: data.tier,
        monthly_token_limit: data.tier === 'free' ? 10000 : 
                             data.tier === 'plus' ? 50000 :
                             data.tier === 'pro' ? 100000 : -1,
      };
      setUser(userData);
      
      // Persist to storage
      localStorage.setItem('rose_access_token', data.access_token);
      localStorage.setItem('rose_refresh_token', data.refresh_token);
      localStorage.setItem('rose_user', JSON.stringify(userData));
      
      return data;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [baseURL]);

  const register = useCallback(async (email: string, password: string, tier: string = 'free') => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${baseURL}/api/v1/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, tier }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Registration failed');
      }

      const data = await response.json();
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      
      const userData: User = {
        user_id: data.user_id,
        email: data.email,
        tier: data.tier,
        monthly_token_limit: tier === 'free' ? 10000 : 
                               tier === 'plus' ? 50000 :
                               tier === 'pro' ? 100000 : -1,
      };
      setUser(userData);
      
      localStorage.setItem('rose_access_token', data.access_token);
      localStorage.setItem('rose_refresh_token', data.refresh_token);
      localStorage.setItem('rose_user', JSON.stringify(userData));
      
      return data;
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [baseURL]);

  const logout = useCallback(() => {
    setAccessToken(null);
    setRefreshToken(null);
    setUser(null);
    setQuota(null);
    localStorage.removeItem('rose_access_token');
    localStorage.removeItem('rose_refresh_token');
    localStorage.removeItem('rose_user');
  }, []);

  const refreshAccessToken = useCallback(async () => {
    try {
      const response = await fetch(`${baseURL}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        throw new Error('Token refresh failed');
      }

      const data = await response.json();
      setAccessToken(data.access_token);
      localStorage.setItem('rose_access_token', data.access_token);
      
      return data;
    } catch (err) {
      // Refresh failed, force logout
      logout();
      throw err;
    }
  }, [refreshToken, baseURL, logout]);

  const fetchQuota = useCallback(async () => {
    if (!accessToken || !user) return;
    
    try {
      const response = await fetch(`${baseURL}/api/v1/usage/status`, {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'User-Id': user.user_id,
        },
      });

      if (response.ok) {
        const data = await response.json();
        setQuota(data);
      }
    } catch (err) {
      console.error('Failed to fetch quota:', err);
    }
  }, [accessToken, user, baseURL]);

  const sendTriageRequest = useCallback(async (
    text: string,
    sessionId: string,
    conversationHistory: Array<{role: string; content: string}> = []
  ): Promise<TriageResponse> => {
    if (!accessToken) {
      throw new Error('Not authenticated');
    }

    // Pre-flight quota check
    if (quota && !quota.data.unlimited && quota.data.remaining < 2000) {
      throw new Error(
        `Insufficient quota. Remaining: ${quota.data.remaining} tokens. ` +
        'Please upgrade your plan.'
      );
    }

    const response = await fetch(`${baseURL}/api/v1/avatar/interact`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'Session-Id': sessionId,
      },
      body: JSON.stringify({
        current_input_type: 'text',
        current_input_text: text,
        conversation_history: conversationHistory,
        current_input_language: 'en',
        response_mode: 'text',
      }),
    });

    if (response.status === 429) {
      const errorData = await response.json();
      throw new Error(errorData.message || 'Quota exceeded');
    }

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Request failed');
    }

    const data = await response.json();
    
    // Update quota after successful request
    await fetchQuota();
    
    return data;
  }, [accessToken, quota, baseURL, fetchQuota]);

  return {
    user,
    loading,
    error,
    quota,
    login,
    register,
    logout,
    refreshAccessToken,
    sendTriageRequest,
    fetchQuota,
  };
}
```

### React Component Example

```tsx
// components/TriageChat.tsx
import React, { useState } from 'react';
import { useROSE } from '../hooks/useROSE';

export function TriageChat() {
  const { user, quota, sendTriageRequest, fetchQuota } = useROSE('https://sebukpor-rose-triage-backend.hf.space');
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Array<{role: string; content: string}>>([]);
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    setIsLoading(true);
    
    try {
      const userMessage = { role: 'user', content: input };
      setMessages(prev => [...prev, userMessage]);
      
      const response = await sendTriageRequest(input, sessionId, messages);
      
      const assistantMessage = {
        role: 'assistant',
        content: response.patient_response.text,
      };
      setMessages(prev => [...prev, assistantMessage]);
      
      // Log token usage
      console.log('Tokens used:', response.token_usage.total_billable_tokens);
      
      // Check if we need to show quota warning
      if (quota && quota.data.percentage_used > 80) {
        alert(`Warning: You've used ${quota.data.percentage_used}% of your monthly quota!`);
      }
      
      setInput('');
    } catch (error) {
      if (error.message.includes('quota')) {
        alert('Quota exceeded. Please upgrade your plan to continue.');
        // Navigate to pricing page
      } else {
        alert('Request failed: ' + error.message);
      }
      // Remove failed message
      setMessages(prev => prev.slice(0, -1));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="triage-chat">
      <div className="quota-bar">
        {quota && !quota.data.unlimited && (
          <>
            <span>Used: {quota.data.current_usage}/{quota.data.monthly_limit}</span>
            <progress value={quota.data.percentage_used} max="100" />
            <span>{quota.data.days_remaining} days left</span>
          </>
        )}
      </div>

      <div className="messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {isLoading && <div className="message assistant">Typing...</div>}
      </div>

      <form onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe your symptoms..."
          disabled={isLoading || (quota && !quota.data.unlimited && quota.data.remaining < 100)}
        />
        <button type="submit" disabled={isLoading}>Send</button>
      </form>
    </div>
  );
}
```

---

## 📱 Mobile App Integration

### React Native Example

```typescript
// App.tsx (React Native)
import React, { useEffect, useState } from 'react';
import { View, Text, TextInput, Button, Alert, ScrollView } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API_BASE = 'https://sebukpor-rose-triage-backend.hf.space';

export default function App() {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<any[]>([]);
  const [quota, setQuota] = useState<any>(null);

  useEffect(() => {
    loadTokens();
  }, []);

  const loadTokens = async () => {
    try {
      const token = await AsyncStorage.getItem('rose_access_token');
      const uid = await AsyncStorage.getItem('rose_user_id');
      if (token && uid) {
        setAccessToken(token);
        setUserId(uid);
        fetchQuota(token, uid);
      }
    } catch (error) {
      console.error('Failed to load tokens:', error);
    }
  };

  const login = async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) throw new Error('Login failed');

      const data = await response.json();
      setAccessToken(data.access_token);
      setUserId(data.user_id);
      
      await AsyncStorage.setItem('rose_access_token', data.access_token);
      await AsyncStorage.setItem('rose_refresh_token', data.refresh_token);
      await AsyncStorage.setItem('rose_user_id', data.user_id);
      
      fetchQuota(data.access_token, data.user_id);
    } catch (error) {
      Alert.alert('Login Error', error.message);
    }
  };

  const fetchQuota = async (token: string, uid: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/v1/usage/status`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'User-Id': uid,
        },
      });
      
      if (response.ok) {
        const data = await response.json();
        setQuota(data);
      }
    } catch (error) {
      console.error('Failed to fetch quota:', error);
    }
  };

  const sendTriageRequest = async () => {
    if (!accessToken || !userId) {
      Alert.alert('Error', 'Please login first');
      return;
    }

    if (quota && !quota.data.unlimited && quota.data.remaining < 2000) {
      Alert.alert('Quota Warning', 'Insufficient tokens. Please upgrade your plan.');
      return;
    }

    setMessages(prev => [...prev, { role: 'user', content: input }]);
    
    try {
      const response = await fetch(`${API_BASE}/api/v1/avatar/interact`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${accessToken}`,
          'User-Id': userId,
        },
        body: JSON.stringify({
          current_input_type: 'text',
          current_input_text: input,
          conversation_history: messages,
          current_input_language: 'en',
          response_mode: 'text',
        }),
      });

      if (response.status === 429) {
        const errorData = await response.json();
        Alert.alert('Quota Exceeded', errorData.message);
        return;
      }

      if (!response.ok) throw new Error('Request failed');

      const data = await response.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.patient_response.text }]);
      setInput('');
      
      // Refresh quota
      fetchQuota(accessToken, userId);
      
    } catch (error) {
      Alert.alert('Error', error.message);
      setMessages(prev => prev.slice(0, -1));
    }
  };

  if (!accessToken) {
    return (
      <View style={{ padding: 20 }}>
        <Text>Login to ROSE Triage</Text>
        <TextInput placeholder="Email" keyboardType="email-address" />
        <TextInput placeholder="Password" secureTextEntry />
        <Button title="Login" onPress={() => login('user@example.com', 'password')} />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, padding: 20 }}>
      {quota && !quota.data.unlimited && (
        <View style={{ marginBottom: 10 }}>
          <Text>
            Quota: {quota.data.current_usage}/{quota.data.monthly_limit} 
            ({quota.data.percentage_used.toFixed(1)}% used)
          </Text>
        </View>
      )}
      
      <ScrollView style={{ flex: 1 }}>
        {messages.map((msg, idx) => (
          <View key={idx} style={{ marginVertical: 5 }}>
            <Text style={{ fontWeight: 'bold' }}>{msg.role}:</Text>
            <Text>{msg.content}</Text>
          </View>
        ))}
      </ScrollView>
      
      <TextInput
        value={input}
        onChangeText={setInput}
        placeholder="Describe your symptoms..."
        style={{ borderWidth: 1, padding: 10, marginBottom: 10 }}
      />
      <Button title="Send" onPress={sendTriageRequest} disabled={!input.trim()} />
    </View>
  );
}
```

---

## ⚙️ Environment Configuration

### Required Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | Supabase PostgreSQL connection string | - | ✅ |
| `JWT_SECRET_KEY` | Secret for JWT signing (HS256) | - | ✅ |
| `GEMINI_API_KEY` | Google Gemini API key | - | ✅ |
| `JWT_EXPIRATION_DAYS` | Access token expiration | 30 | ❌ |
| `JWT_REFRESH_EXPIRATION_DAYS` | Refresh token expiration | 90 | ❌ |
| `ALLOWED_TIERS` | Comma-separated list of allowed tiers | free,plus,pro,enterprise,admin | ❌ |

### Frontend Environment Variables

```env
# .env.example for frontend
REACT_APP_ROSE_API_URL=https://sebukpor-rose-triage-backend.hf.space
REACT_APP_ROSE_WS_URL=wss://sebukpor-rose-triage-backend.hf.space
```

---

## 🚨 Error Handling & Status Codes

### HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | OK | Request succeeded |
| 201 | Created | Resource created (registration) |
| 400 | Bad Request | Invalid input, check request body |
| 401 | Unauthorized | Invalid/missing token, refresh or re-login |
| 403 | Forbidden | Insufficient permissions |
| 413 | Payload Too Large | Audio/image file too large |
| 422 | Unprocessable Entity | Validation error, check schema |
| 429 | Too Many Requests | Quota exceeded, upgrade or wait |
| 500 | Internal Server Error | Clinical safety protocol or server error |
| 503 | Service Unavailable | Backend down, retry later |

### Error Response Schema

```json
{
  "error": "client_error | server_error | clinical_safety | quota_exceeded",
  "message": "Human-readable error description",
  "suggestion": "Recommended action",
  "reference_id": "err-xxxxx"  // For support tickets
}
```

### Retry Strategy

```typescript
async function fetchWithRetry(url: string, options: RequestInit, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const response = await fetch(url, options);
      
      if (response.status === 429) {
        // Quota exceeded, don't retry
        throw new Error('Quota exceeded');
      }
      
      if (response.status === 503) {
        // Service unavailable, retry with backoff
        const delay = Math.pow(2, i) * 1000;
        await new Promise(resolve => setTimeout(resolve, delay));
        continue;
      }
      
      return response;
    } catch (error) {
      if (i === maxRetries - 1) throw error;
    }
  }
}
```

---

## ✅ Best Practices & Checklist

### Pre-Launch Checklist

- [ ] Implement token refresh logic (before expiration)
- [ ] Add quota status display in UI
- [ ] Show warnings at 80%, 90%, 95% quota usage
- [ ] Handle 429 errors gracefully with upgrade prompts
- [ ] Secure token storage (no localStorage in production)
- [ ] Implement session management (Session-Id header)
- [ ] Add error boundaries and fallback UI
- [ ] Test offline scenarios
- [ ] Validate all user inputs before sending
- [ ] Implement request debouncing for chat
- [ ] Add loading states for all async operations
- [ ] Log token usage for analytics
- [ ] Test with different tiers (free, plus, pro)

### Performance Optimization

1. **Use Context Caching**: Maintain conversation history to leverage Gemini's context cache
2. **Batch Requests**: Combine multiple user inputs when possible
3. **Stream Responses**: Use `/interact/stream` for better perceived performance
4. **Cache Static Data**: Cache pricing tiers, don't fetch on every render
5. **Debounce User Input**: Wait 300ms before sending typing indicators

### Security Checklist

- [ ] Use HTTPS in production
- [ ] Implement CSRF protection for web apps
- [ ] Sanitize all user inputs
- [ ] Don't log sensitive data (tokens, passwords)
- [ ] Implement rate limiting on client side
- [ ] Use Content Security Policy (CSP) headers
- [ ] Validate JWT tokens on every request
- [ ] Implement token blacklisting on logout

---

## ✅ Known Limitations - RESOLVED (v1.1)

### Improvements Implemented

The following limitations have been addressed in this version:

1. **✅ User-Id Header Redundancy - FIXED**
   
   **Previous Issue**: The `/api/v1/usage/status` and `/api/v1/usage/history` endpoints required a `User-Id` header, creating potential for mismatch with JWT token.
   
   **Solution**: New endpoints extract `user_id` from JWT token automatically:
   - `GET /api/v1/usage/status` - Uses authenticated user from JWT
   - `GET /api/v1/usage/history` - Uses authenticated user from JWT + pagination
   - `POST /api/v1/usage/tier/upgrade` - Self-service tier upgrades
   - `GET /api/v1/usage/check` - Pre-flight quota checking
   
   **Legacy Endpoints**: Old endpoints still available but marked as deprecated (`deprecated=True` in OpenAPI spec). Will be removed in v2.0.
   
   **Migration Guide**:
   ```typescript
   // ❌ OLD (Deprecated)
   const response = await fetch('/api/v1/usage/status', {
     headers: {
       'Authorization': `Bearer ${token}`,
       'User-Id': userId  // Required but redundant
     }
   });
   
   // ✅ NEW (Recommended)
   const response = await fetch('/api/v1/usage/status', {
     headers: {
       'Authorization': `Bearer ${token}`
       // User-Id extracted from JWT automatically
     }
   });
   ```

2. **✅ No Pagination for Usage History - FIXED**
   
   **Previous Issue**: The `/api/v1/usage/history` endpoint returned all records, potentially large datasets.
   
   **Solution**: Added pagination parameters:
   - `page`: Page number (default: 1)
   - `page_size`: Items per page (10-100, default: 50)
   
   **Response includes**:
   ```json
   {
     "total_pages": 5,
     "has_more": true,
     "page": 1,
     "page_size": 50,
     "records": [...]
   }
   ```

3. **✅ Missing Tier Upgrade Endpoint - FIXED**
   
   **Previous Issue**: No API endpoint to upgrade user tier directly.
   
   **Solution**: Added `POST /api/v1/usage/tier/upgrade`:
   ```typescript
   const upgradeTier = async (newTier: string) => {
     const response = await fetch('/api/v1/usage/tier/upgrade', {
       method: 'POST',
       headers: {
         'Authorization': `Bearer ${token}`,
         'Content-Type': 'application/json'
       },
       body: JSON.stringify({ new_tier: newTier })
     });
     
     // Returns: { success, old_tier, new_tier, message }
   };
   ```
   
   **Features**:
   - Prevents downgrades (contact support for downgrades)
   - Enterprise tier requires admin approval
   - Updates database and usage limiter cache
   - Returns clear error messages

4. **✅ Admin Usage History Endpoint - NEW**
   
   Added `GET /api/v1/usage/history/admin/{user_id}` for admin users to view any user's usage history. Requires admin privileges.

### Remaining Limitations (Future Versions)

5. **No WebSocket Support**: Real-time communication uses SSE only.
   
   **Workaround**: Use SSE for streaming responses. WebSocket support planned for v2.0.

6. **No Webhook for Quota Alerts**: Frontend must poll for quota status.
   
   **Recommendation**: Implement periodic polling (every 5-10 minutes) or check quota before expensive operations using `GET /api/v1/usage/check`.

7. **No Audio File Upload**: Audio must be base64-encoded.
   
   **Workaround**: Compress audio client-side before encoding. Multipart upload planned for v2.0.

8. **Limited Error Details**: Some validation errors lack field-level details.
   
   **Status**: Being improved incrementally. Check Swagger UI for latest schemas.


## 📞 Support & Resources

- **API Documentation**: https://sebukpor-rose-triage-backend.hf.space/docs#/
- **Swagger UI**: Interactive API testing at `/docs`
- **ReDoc Alternative**: Available at `/redoc`
- **GitHub Issues**: Report bugs and feature requests
- **Email Support**: support@rose-triage.com

---

*This documentation is maintained alongside the ROSE backend codebase. For the latest updates, check the repository.*
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
