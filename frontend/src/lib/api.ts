import { assertBrowserNativeRequest } from '@/features/native-settings/surfaceRegistry'
import { API_BASE_URL } from './constants'

/**
 * Build an API endpoint URL with optional query parameters.
 * Filters out undefined values automatically.
 */
export function buildEndpoint(
  endpoint: string,
  params?: Record<string, string | number | boolean | undefined>
): string {
  if (!params) return endpoint;

  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) {
      searchParams.append(key, String(value));
    }
  });

  const queryString = searchParams.toString();
  return queryString ? `${endpoint}?${queryString}` : endpoint;
}

export interface ApiError {
  message?: string
  detail?: string | { message?: string; block_code?: string; code?: string; msg?: string } | Array<{ msg?: string }>
}

const operatorErrorMessages: Record<string, string> = {
  operator_token_required: 'Enter the Deck operator token to continue.',
  operator_token_invalid: 'The Deck operator token was rejected. Clear it and enter a valid token.',
  operator_token_unconfigured: 'The Deck operator token is not configured on the backend.',
  scope_identity_in_use: 'This repo has active work. Change its identity or base ref only after that work is finished.',
}

function apiErrorMessage(error: ApiError, fallback = 'An error occurred'): string {
  if (typeof error.detail === 'string') return operatorErrorMessages[error.detail] ?? error.detail
  if (Array.isArray(error.detail)) {
    const messages = error.detail.map((item) => item.msg).filter(Boolean)
    if (messages.length > 0) return messages.join(', ')
  }
  if (error.detail && !Array.isArray(error.detail) && typeof error.detail === 'object') {
    if (error.detail.message) return error.detail.message
    if (error.detail.msg) return error.detail.msg
  }
  return error.message || fallback
}

export class ApiHttpError extends Error {
  readonly status: number
  readonly blockCode?: string
  readonly code?: string

  constructor(message: string, status: number, blockCode?: string, code?: string) {
    super(message)
    this.name = 'ApiHttpError'
    this.status = status
    this.blockCode = blockCode
    this.code = code
  }
}

function httpError(response: Response, body: ApiError): ApiHttpError {
  const detail = body.detail
  const blockCode = detail && !Array.isArray(detail) && typeof detail === 'object'
    ? detail.block_code
    : undefined
  return new ApiHttpError(apiErrorMessage(body), response.status, blockCode, detail && !Array.isArray(detail) && typeof detail === 'object' ? detail.code : undefined)
}

export class ApiClient {
  private async request<T>(
    endpoint: string,
    options?: RequestInit
  ): Promise<T> {
    assertBrowserNativeRequest(endpoint, options?.method ?? 'GET')
    const url = `${API_BASE_URL}${endpoint}`

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options?.headers,
        },
      })

      if (!response.ok) {
        const error: ApiError = await response.json().catch(() => ({
          message: `HTTP ${response.status}: ${response.statusText}`,
        }))
        throw httpError(response, error)
      }

      return response.json()
    } catch (error) {
      if (error instanceof Error) {
        throw error
      }
      throw new Error('An unknown error occurred', { cause: error })
    }
  }

  async get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'GET' })
  }

  async post<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  async put<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' })
  }
}

export const api = new ApiClient()

// Helper function for simpler API calls
export async function apiClient<T>(endpoint: string, options?: RequestInit): Promise<T> {
  assertBrowserNativeRequest(endpoint, options?.method ?? 'GET')
    const url = `${API_BASE_URL}${endpoint}`

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    })

    // Handle 204 No Content responses
    if (response.status === 204) {
      return {} as T
    }

    if (!response.ok) {
      const error: ApiError = await response.json().catch(() => ({
        message: `HTTP ${response.status}: ${response.statusText}`,
      }))
      throw httpError(response, error)
    }

    return response.json()
  } catch (error) {
    if (error instanceof Error) {
      throw error
    }
    throw new Error('An unknown error occurred', { cause: error })
  }
}
