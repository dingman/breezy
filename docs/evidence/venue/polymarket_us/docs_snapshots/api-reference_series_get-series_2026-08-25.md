> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Series

> Retrieve all series



## OpenAPI

````yaml /api-reference/oapi-schemas/series-schema.json get /v1/series
openapi: 3.0.3
info:
  title: protos/gateway/series/v1/series.proto
  version: 1.0.0
servers:
  - url: https://gateway.polymarket.us
    description: Production server
security: []
tags:
  - name: SeriesService
paths:
  /v1/series:
    get:
      tags:
        - Series
      summary: Get Series
      description: Retrieve all series
      operationId: SeriesService_GetSeries
      parameters:
        - name: limit
          description: Pagination limit
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: offset
          description: Pagination offset
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: orderBy
          description: Pagination order
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: orderDirection
          description: Pagination order direction
          in: query
          required: false
          schema:
            type: string
        - name: slug
          description: Series slug
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: active
          description: Whether series is active
          in: query
          required: false
          schema:
            type: boolean
        - name: recurrence
          description: Series recurrence pattern
          in: query
          required: false
          schema:
            type: string
        - name: params.limit
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: params.offset
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: params.orderBy
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: params.orderDirection
          in: query
          required: false
          schema:
            type: string
        - name: params.seriesFilters.slug
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: params.seriesFilters.categoriesIds
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: params.seriesFilters.categoriesLabels
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: params.seriesFilters.query
          in: query
          required: false
          schema:
            type: string
        - name: params.seriesFilters.active
          in: query
          required: false
          schema:
            type: boolean
        - name: params.seriesFilters.recurrence
          in: query
          required: false
          schema:
            type: string
        - name: params.tagsFilters.includeTemplate
          in: query
          required: false
          schema:
            type: boolean
        - name: params.tagsFilters.query
          in: query
          required: false
          schema:
            type: string
      responses:
        '200':
          description: List of series
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/gateway.series.v1.GetSeriesResponse'
        '500':
          description: Internal server error
          content:
            application/json:
              schema: {}
components:
  schemas:
    gateway.series.v1.GetSeriesResponse:
      type: object
      properties:
        series:
          type: array
          items:
            $ref: '#/components/schemas/gateway.series.v1.Series'
          description: List of series
      description: Response containing list of series
    gateway.series.v1.Series:
      type: object
      properties:
        id:
          type: string
          description: Unique series identifier
        slug:
          type: string
          description: Series slug for URL
          nullable: true
        title:
          type: string
          description: Series title
          nullable: true
        subtitle:
          type: string
          description: Series subtitle
          nullable: true
        recurrence:
          type: string
          description: Series recurrence pattern
          nullable: true
        image:
          type: string
          description: Series image URL
          nullable: true
        active:
          type: boolean
          description: Whether series is active
          nullable: true
        createdAt:
          type: string
          description: Creation timestamp
          nullable: true
        updatedAt:
          type: string
          description: Last update timestamp
          nullable: true
      description: Series information and configuration

````