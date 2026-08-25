> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Series By ID

> Retrieve a specific series by its ID



## OpenAPI

````yaml /api-reference/oapi-schemas/series-schema.json get /v1/series/id/{id}
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
  /v1/series/id/{id}:
    get:
      tags:
        - Series
      summary: Get Series By ID
      description: Retrieve a specific series by its ID
      operationId: SeriesService_GetSeriesByID
      parameters:
        - name: id
          description: Series ID
          in: path
          required: true
          schema:
            type: integer
            format: int32
      responses:
        '200':
          description: Series details
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/gateway.series.v1.GetSeriesByIDResponse'
        '404':
          description: Series not found
          content:
            application/json:
              schema: {}
        '500':
          description: Internal server error
          content:
            application/json:
              schema: {}
components:
  schemas:
    gateway.series.v1.GetSeriesByIDResponse:
      type: object
      properties:
        series:
          $ref: '#/components/schemas/gateway.series.v1.Series'
      description: Response containing series details
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