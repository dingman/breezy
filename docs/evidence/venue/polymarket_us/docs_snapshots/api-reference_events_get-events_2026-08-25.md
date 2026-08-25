> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Events

> Retrieve all events



## OpenAPI

````yaml /api-reference/oapi-schemas/events-schema.json get /v1/events
openapi: 3.0.3
info:
  title: protos/gateway/events/v1/events.proto
  version: 1.0.0
servers:
  - url: https://gateway.polymarket.us
    description: Production server
security: []
tags:
  - name: EventsService
paths:
  /v1/events:
    get:
      tags:
        - Events
      summary: Get Events
      description: Retrieve all events
      operationId: EventsService_GetEvents
      parameters:
        - name: limit
          description: Maximum number of events to return
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: offset
          description: Number of events to skip for pagination
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: orderBy
          description: Fields to order results by
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: orderDirection
          description: Order direction (asc or desc)
          in: query
          required: false
          schema:
            type: string
        - name: id
          description: Filter by event IDs
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: slug
          description: Filter by event slugs
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: archived
          description: Filter by archived status
          in: query
          required: false
          schema:
            type: boolean
        - name: active
          description: Filter by active status
          in: query
          required: false
          schema:
            type: boolean
        - name: closed
          description: Filter by closed status
          in: query
          required: false
          schema:
            type: boolean
        - name: liquidityMin
          description: Minimum liquidity filter
          in: query
          required: false
          schema:
            type: number
            format: double
        - name: liquidityMax
          description: Maximum liquidity filter
          in: query
          required: false
          schema:
            type: number
            format: double
        - name: volumeMin
          description: Minimum volume filter
          in: query
          required: false
          schema:
            type: number
            format: double
        - name: volumeMax
          description: Maximum volume filter
          in: query
          required: false
          schema:
            type: number
            format: double
        - name: startDateMin
          description: Minimum start date filter
          in: query
          required: false
          schema:
            type: string
        - name: startDateMax
          description: Maximum start date filter
          in: query
          required: false
          schema:
            type: string
        - name: endDateMin
          description: Minimum end date filter
          in: query
          required: false
          schema:
            type: string
        - name: endDateMax
          description: Maximum end date filter
          in: query
          required: false
          schema:
            type: string
        - name: relatedTags
          description: Include related tags
          in: query
          required: false
          schema:
            type: boolean
        - name: tagSlug
          description: Filter by tag slug
          in: query
          required: false
          schema:
            type: string
        - name: userId
          description: Filter by user ID
          in: query
          required: false
          schema:
            type: string
        - name: featured
          description: Filter by featured status
          in: query
          required: false
          schema:
            type: boolean
        - name: seriesId
          description: Filter by series IDs
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: eventDate
          description: Filter by event date
          in: query
          required: false
          schema:
            type: string
        - name: startTimeMin
          description: Minimum start time filter
          in: query
          required: false
          schema:
            type: string
        - name: startTimeMax
          description: Maximum start time filter
          in: query
          required: false
          schema:
            type: string
        - name: excludeTagId
          description: Tag IDs to exclude
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: featuredOrder
          description: Order by featured position
          in: query
          required: false
          schema:
            type: boolean
        - name: includeTemplate
          description: Include template events
          in: query
          required: false
          schema:
            type: boolean
        - name: recurrence
          description: Filter by recurrence type
          in: query
          required: false
          schema:
            type: string
        - name: gameId
          description: Filter by game ID
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: rescheduledFromGameId
          description: Filter by rescheduled from game ID
          in: query
          required: false
          schema:
            type: integer
            format: int32
        - name: period
          description: Filter by event period
          in: query
          required: false
          schema:
            type: string
        - name: finishedTimestampMin
          description: Minimum finished timestamp filter
          in: query
          required: false
          schema:
            type: string
        - name: finishedTimestampMax
          description: Maximum finished timestamp filter
          in: query
          required: false
          schema:
            type: string
        - name: ended
          description: Filter by ended status
          in: query
          required: false
          schema:
            type: boolean
        - name: sportradarGameId
          description: Filter by Sportradar game ID
          in: query
          required: false
          schema:
            type: string
        - name: excludeSeriesId
          description: Series IDs to exclude
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: resolution
          description: Filter by resolution status
          in: query
          required: false
          schema:
            type: boolean
        - name: categories
          description: Filter by categories
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: marketTypes
          description: Filter by market types
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
        - name: live
          description: Filter by live status
          in: query
          required: false
          schema:
            type: boolean
        - name: excludeEventId
          description: Event IDs to exclude
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: includeHidden
          description: 'Include hidden events (default: false)'
          in: query
          required: false
          schema:
            type: boolean
        - name: tagIds
          description: Filter by tag IDs
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: integer
              format: int32
        - name: sportsMarketTypes
          description: >-
            Filter by fine-grained sports_market_type (e.g. moneyline,
            drawable_outcome, soccer_game_to_advance)
          in: query
          required: false
          explode: true
          schema:
            type: array
            items:
              type: string
      responses:
        '200':
          description: List of events
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/gateway.events.v1.GetEventsResponse'
        '500':
          description: Internal server error
          content:
            application/json:
              schema: {}
components:
  schemas:
    gateway.events.v1.GetEventsResponse:
      type: object
      properties:
        events:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.Event'
          description: List of events
      description: Response containing list of events
    gateway.market.v1.Event:
      type: object
      properties:
        id:
          type: string
          description: Unique event identifier
        ticker:
          type: string
          description: Event ticker symbol
          nullable: true
        slug:
          type: string
          description: Event slug for URL
          nullable: true
        title:
          type: string
          description: Event title
          nullable: true
        subtitle:
          type: string
          description: Event subtitle
          nullable: true
        description:
          type: string
          description: Event description
          nullable: true
        resolutionSource:
          type: string
          description: Source for event resolution
          nullable: true
        startDate:
          type: string
          description: Event start date
          nullable: true
        creationDate:
          type: string
          description: Event creation date
          nullable: true
        endDate:
          type: string
          description: Event end date
          nullable: true
        image:
          type: string
          description: Event image URL
          nullable: true
        active:
          type: boolean
          description: Whether event is active
          nullable: true
        closed:
          type: boolean
          description: Whether event is closed
          nullable: true
        archived:
          type: boolean
          description: Whether event is archived
          nullable: true
        liquidity:
          type: number
          format: decimal
          description: Event liquidity
          nullable: true
        volume:
          type: number
          format: decimal
          description: Event volume
          nullable: true
        openInterest:
          type: number
          format: decimal
          description: Open interest
          nullable: true
        category:
          type: string
          description: Event category
          nullable: true
        subcategory:
          type: string
          description: Event subcategory
          nullable: true
        createdAt:
          type: string
          description: Creation timestamp
          nullable: true
        updatedAt:
          type: string
          description: Last update timestamp
          nullable: true
        volume24hr:
          type: number
          format: decimal
          description: 24-hour volume
          nullable: true
        volume1wk:
          type: number
          format: decimal
          description: One week volume
          nullable: true
        volume1mo:
          type: number
          format: decimal
          description: One month volume
          nullable: true
        volume1yr:
          type: number
          format: decimal
          description: One year volume
          nullable: true
        closedTime:
          type: string
          description: Event close time
          nullable: true
        eventDate:
          type: string
          description: Event date
          nullable: true
        startTime:
          type: string
          description: Event start time
          nullable: true
        seriesSlug:
          type: string
          description: Series slug
          nullable: true
        score:
          type: string
          description: Event score
          nullable: true
        elapsed:
          type: string
          description: Elapsed time
          nullable: true
        period:
          type: string
          description: Event period
          nullable: true
        live:
          type: boolean
          description: Whether event is live
          nullable: true
        ended:
          type: boolean
          description: Whether event has ended
          nullable: true
        finishedTimestamp:
          type: string
          description: Finished timestamp
          nullable: true
        featuredOrder:
          type: integer
          format: int32
          description: Featured order
          nullable: true
        markets:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.Market'
          description: Associated markets
        gameId:
          type: integer
          format: int32
          description: ID taken from our sports provider
          nullable: true
        rescheduledFromGameId:
          type: integer
          format: int32
          description: Rescheduled ID taken from our sports provider
          nullable: true
        sportradarGameId:
          type: string
          description: Sportradar game ID
          nullable: true
        eventState:
          $ref: '#/components/schemas/gateway.market.v1.EventState'
        hidden:
          type: boolean
          description: Whether event is hidden
          nullable: true
        tags:
          type: array
          items:
            $ref: '#/components/schemas/gateway.tags.v1.Tag'
          description: Associated tags
        teams:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.Team'
          description: Associated teams
        metadata:
          $ref: '#/components/schemas/gateway.market.v1.EventMetadata'
        sortType:
          type: string
          description: Sort type for ordering markets within event
          nullable: true
        marketGroups:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.EventMarketGroup'
          description: >-
            Flat list of market groups forming a hierarchy via parent_id (only
            when groups=true)
        primaryTag:
          $ref: '#/components/schemas/gateway.tags.v1.Tag'
        secondaryTag:
          $ref: '#/components/schemas/gateway.tags.v1.Tag'
        primaryTagSlug:
          type: string
          description: >-
            Raw upstream primary tag slug override (admin-only; omitted on
            public reads)
          nullable: true
        secondaryTagSlug:
          type: string
          description: >-
            Raw upstream secondary tag slug override (admin-only; omitted on
            public reads)
          nullable: true
        livestreamUrl:
          type: string
          description: Livestream URL for the event
          nullable: true
        featureAvailability:
          $ref: '#/components/schemas/gateway.market.v1.EventFeatureAvailability'
      description: Event information and configuration
    gateway.market.v1.Market:
      type: object
      properties:
        id:
          type: string
          description: Unique market identifier
        question:
          type: string
          description: Market question
          nullable: true
        slug:
          type: string
          description: Market slug for URL
          nullable: true
        endDate:
          type: string
          description: Market end date
          nullable: true
        category:
          type: string
          description: Market category
          nullable: true
        startDate:
          type: string
          description: Market start date
          nullable: true
        image:
          type: string
          description: Market image URL
          nullable: true
        description:
          type: string
          description: Market description
          nullable: true
        active:
          type: boolean
          description: Whether market is active
          nullable: true
        marketType:
          type: string
          description: 'Type of market (deprecated). Options: moneyline, spreads, totals'
          nullable: true
          deprecated: true
        closed:
          type: boolean
          description: Whether market is closed
          nullable: true
        createdAt:
          type: string
          description: Creation timestamp
          nullable: true
        updatedAt:
          type: string
          description: Last update timestamp
          nullable: true
        archived:
          type: boolean
          description: Whether market is archived
          nullable: true
          deprecated: true
        orderPriceMinTickSize:
          type: number
          format: decimal
          description: Minimum tick size for order price
          nullable: true
        gameStartTime:
          type: string
          description: Game start time
          nullable: true
          deprecated: true
        manualActivation:
          type: boolean
          description: Whether manual activation is required
          nullable: true
          deprecated: true
        sportsMarketType:
          type: string
          description: Sports market type
          nullable: true
        line:
          type: number
          format: decimal
          description: Line value
          nullable: true
        marketSides:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.MarketSide'
          description: Market sides
        outcomes:
          type: string
          description: Outcomes JSON
          nullable: true
          deprecated: true
        outcomePrices:
          type: string
          description: Outcome prices JSON
          nullable: true
          deprecated: true
        ep3Status:
          type: string
          description: EP3 status
          nullable: true
        sportsMarketTypeV2:
          allOf:
            - $ref: '#/components/schemas/gateway.market.v1.SportsMarketType'
          deprecated: true
        hidden:
          type: boolean
          description: Whether market is hidden
          nullable: true
        tags:
          type: array
          items:
            $ref: '#/components/schemas/gateway.tags.v1.Tag'
          description: Associated tags
        title:
          type: string
          description: Market title
          nullable: true
        subtitle:
          type: string
          description: Market subtitle
          nullable: true
        color:
          type: string
          description: Market color
          nullable: true
        darkColor:
          type: string
          description: Market dark mode color
          nullable: true
        subjectId:
          type: integer
          format: int32
          description: Subject ID
          nullable: true
        subject:
          $ref: '#/components/schemas/gateway.market.v1.Subject'
        feeCoefficient:
          type: number
          format: decimal
          description: Fee coefficient
          nullable: true
        spreadTotalSuffix:
          type: string
          description: Spread/total suffix for UI display (e.g. points, goals, runs)
          nullable: true
        sortOrder:
          type: integer
          format: int32
          description: Sort order for market within event
          nullable: true
        bestBidQuote:
          $ref: '#/components/schemas/gateway.types.v1.Amount'
        bestAskQuote:
          $ref: '#/components/schemas/gateway.types.v1.Amount'
        metadata:
          type: object
          description: >-
            Opaque metadata object — internal-use only, shape is not part of the
            public contract
          nullable: true
        titleShort:
          type: string
          description: >-
            Compact display title computed at serialization time (e.g. 'DET -5.5
            F5', 'Over 5.5 F5'). Falls back to title.
          nullable: true
        ep3SyncedAt:
          type: string
          description: Timestamp when this market was last synced from EP3
          nullable: true
        minimumTradeQty:
          type: number
          format: decimal
          description: >-
            Minimum order quantity in contracts (e.g. 0.01 = 1% of a contract,
            1.0 = one whole contract).
          nullable: true
        volume:
          type: number
          format: decimal
          description: Market volume (lifetime, in shares)
          nullable: true
        volume24hr:
          type: number
          format: decimal
          description: 24-hour market volume (in shares)
          nullable: true
        volume1wk:
          type: number
          format: decimal
          description: One week market volume (in shares)
          nullable: true
        volume1mo:
          type: number
          format: decimal
          description: One month market volume (in shares)
          nullable: true
        volume1yr:
          type: number
          format: decimal
          description: One year market volume (in shares)
          nullable: true
        rulesDisclaimer:
          type: string
          description: >-
            Short 'understanding the rules' disclaimer for this market type,
            computed at serialization time. Omitted when the market's
            sports_market_type has no disclaimer.
          nullable: true
      description: Market information and configuration
    gateway.market.v1.EventState:
      type: object
      properties:
        id:
          type: integer
          format: int32
        gameId:
          type: integer
          format: int32
          nullable: true
        sportradarGameId:
          type: string
          nullable: true
        type:
          type: string
        createdAt:
          type: string
          format: date-time
          nullable: true
        updatedAt:
          type: string
          format: date-time
          nullable: true
        score:
          type: string
          nullable: true
        elapsed:
          type: string
          nullable: true
        period:
          type: string
          nullable: true
        live:
          type: boolean
          nullable: true
        ended:
          type: boolean
          nullable: true
        finishedTimestamp:
          type: string
          format: date-time
          nullable: true
        footballState:
          $ref: '#/components/schemas/gateway.market.v1.FootballState'
        ufcState:
          $ref: '#/components/schemas/gateway.market.v1.UFCState'
        tennisState:
          $ref: '#/components/schemas/gateway.market.v1.TennisState'
        baseballState:
          $ref: '#/components/schemas/gateway.market.v1.BaseballState'
        cricketState:
          $ref: '#/components/schemas/gateway.market.v1.CricketState'
        soccerState:
          $ref: '#/components/schemas/gateway.market.v1.SoccerState'
        mainSpreadLine:
          type: number
          format: double
          description: Main spread line
          title: Lines
          nullable: true
        mainTotalLine:
          type: number
          format: double
          description: Main total line
          nullable: true
        marketGroupStats:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.MarketGroupStat'
          description: Per-market-group current line and count
    gateway.tags.v1.Tag:
      type: object
      properties:
        id:
          type: string
          description: Unique tag identifier
        label:
          type: string
          description: Tag label
          nullable: true
        slug:
          type: string
          description: Tag slug for URL
          nullable: true
        createdAt:
          type: string
          description: Creation timestamp
          nullable: true
        updatedAt:
          type: string
          description: Last update timestamp
          nullable: true
        image:
          type: string
          description: Tag image URL
          nullable: true
        tradable:
          type: boolean
          description: Whether the tag is tradable
          nullable: true
        league:
          $ref: '#/components/schemas/gateway.tags.v1.TagLeague'
        sport:
          $ref: '#/components/schemas/gateway.tags.v1.TagSport'
        parentId:
          type: integer
          format: int32
          description: Parent tag ID
          nullable: true
        subtags:
          type: array
          items:
            type: object
            description: Nested object (recursive)
          description: Child subtags
    gateway.market.v1.Team:
      type: object
      properties:
        id:
          type: integer
          format: int32
        name:
          type: string
        abbreviation:
          type: string
        league:
          type: string
        record:
          type: string
        logo:
          type: string
        alias:
          type: string
        safeName:
          type: string
        homeIcon:
          type: string
          nullable: true
        awayIcon:
          type: string
          nullable: true
        colorPrimary:
          type: string
          nullable: true
        providerId:
          type: integer
          format: int32
          nullable: true
        ordering:
          type: string
          nullable: true
        longIcon:
          type: string
          nullable: true
        shortIcon:
          type: string
          nullable: true
        displayAbbreviation:
          type: string
          nullable: true
        ranking:
          type: string
          format: int64
          nullable: true
        conference:
          type: string
          nullable: true
        providerIds:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.SportsTeamProvider'
        longIconDark:
          type: string
          nullable: true
        shortIconDark:
          type: string
          nullable: true
        color:
          $ref: '#/components/schemas/gateway.market.v1.ResolvedColor'
    gateway.market.v1.EventMetadata:
      type: object
      properties:
        gameState:
          $ref: '#/components/schemas/gateway.market.v1.EventState'
        latestGameUpdate:
          $ref: '#/components/schemas/gateway.market.v1.GameUpdate'
    gateway.market.v1.EventMarketGroup:
      type: object
      properties:
        id:
          type: string
          description: >-
            Unique identifier for this group (path-based, e.g.
            'player-props/home-runs/yankees')
        title:
          type: string
          description: Display title for this group
        subtitle:
          type: string
          description: Optional display subtitle for this group
          nullable: true
        parentId:
          type: string
          description: ID of the parent group (null for root groups, which act as tabs)
          nullable: true
        order:
          type: integer
          format: int32
          description: Sort order among siblings with the same parent
        marketIds:
          type: array
          items:
            type: string
          description: Ordered market ID references into event.markets
        line:
          type: number
          format: decimal
          description: Line value for this group
          nullable: true
        current:
          type: number
          format: decimal
          description: Current line value
          nullable: true
        searchable:
          type: boolean
          description: Whether this group's markets are searchable
          nullable: true
        showAllThreshold:
          type: integer
          format: int32
          description: Number of markets to show before collapsing with a 'show all' button
          nullable: true
        showMarketImages:
          type: boolean
          description: Whether clients should render market images for this group
          nullable: true
    gateway.market.v1.EventFeatureAvailability:
      type: object
      properties:
        lineups:
          type: boolean
          description: Lineups are generally available for this event
        timeline:
          type: boolean
          description: >-
            Live timeline including statistics and play-by-play is generally
            available for this event
      description: Data surfaces available for this event
    gateway.market.v1.MarketSide:
      type: object
      properties:
        id:
          type: string
          description: Market side ID
        marketSideType:
          $ref: '#/components/schemas/gateway.market.v1.MarketSideType'
        identifier:
          type: string
          description: Market side identifier
          nullable: true
        createdAt:
          type: string
          description: Creation timestamp
          nullable: true
        updatedAt:
          type: string
          description: Last update timestamp
          nullable: true
        description:
          type: string
          description: Market side description
          nullable: true
        price:
          type: string
          description: Market side price
          nullable: true
        marketId:
          type: integer
          format: int32
          description: Market ID
        long:
          type: boolean
          description: Whether market side is the long or short side of the market
          nullable: true
        teamId:
          type: integer
          format: int32
          description: Team ID
          nullable: true
        team:
          allOf:
            - $ref: '#/components/schemas/gateway.market.v1.Team'
          deprecated: true
        quote:
          $ref: '#/components/schemas/gateway.types.v1.Amount'
        tradable:
          type: boolean
          description: Whether this side can be traded
          nullable: true
      description: Market position information
    gateway.market.v1.SportsMarketType:
      type: string
      enum:
        - SPORTS_MARKET_TYPE_MONEYLINE
        - SPORTS_MARKET_TYPE_SPREAD
        - SPORTS_MARKET_TYPE_TOTAL
        - SPORTS_MARKET_TYPE_PROP
        - SPORTS_MARKET_TYPE_FUTURE
        - SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME
    gateway.market.v1.Subject:
      type: object
      properties:
        id:
          type: integer
          format: int32
          description: Subject ID
        name:
          type: string
          description: Subject name
        displayName:
          type: string
          description: Subject display name
          nullable: true
        description:
          type: string
          description: Subject description
          nullable: true
        subjectType:
          type: string
          description: Subject type (nominee, player, team, candidate, golf_player)
        image:
          type: string
          description: Subject image URL
          nullable: true
        color:
          type: string
          description: Subject color
          nullable: true
        darkColor:
          type: string
          description: Subject dark mode color
          nullable: true
        createdAt:
          type: string
          description: Creation timestamp
          nullable: true
        updatedAt:
          type: string
          description: Last update timestamp
          nullable: true
        slug:
          type: string
          description: Subject slug for URL
          nullable: true
      description: Subject information
    gateway.types.v1.Amount:
      type: object
      properties:
        value:
          type: string
          format: decimal
          example: 123.45
          description: The amount as a decimal string.
        currency:
          type: string
          description: The currency code
      description: Represents a monetary amount with its currency.
      required:
        - value
        - currency
    gateway.market.v1.FootballState:
      type: object
      properties:
        down:
          type: integer
          format: int32
          nullable: true
        yard:
          type: integer
          format: int32
          nullable: true
        possessionProviderId:
          type: string
          nullable: true
    gateway.market.v1.UFCState:
      type: object
      properties:
        weightClass:
          type: string
          nullable: true
        cardSegment:
          type: string
          nullable: true
        eventLogo:
          type: string
          nullable: true
        rounds:
          type: integer
          format: int32
          nullable: true
        order:
          type: integer
          format: int32
          nullable: true
    gateway.market.v1.TennisState:
      type: object
      properties:
        tournamentName:
          type: string
          nullable: true
        round:
          type: string
          nullable: true
    gateway.market.v1.BaseballState:
      type: object
      properties:
        balls:
          type: integer
          format: int32
          nullable: true
        strikes:
          type: integer
          format: int32
          nullable: true
        outs:
          type: integer
          format: int32
          nullable: true
        onFirst:
          type: boolean
          nullable: true
        onSecond:
          type: boolean
          nullable: true
        onThird:
          type: boolean
          nullable: true
        inningHalf:
          type: string
          nullable: true
    gateway.market.v1.CricketState:
      type: object
      properties:
        innings:
          type: array
          items:
            $ref: '#/components/schemas/gateway.market.v1.CricketInnings'
        currentInnings:
          type: integer
          format: int32
          nullable: true
        totalOvers:
          type: integer
          format: int32
          nullable: true
        phase:
          type: string
          nullable: true
        chase:
          $ref: '#/components/schemas/gateway.market.v1.CricketChase'
    gateway.market.v1.SoccerState:
      type: object
      properties:
        shootoutAttempts:
          type: array
          items:
            $ref: >-
              #/components/schemas/gateway.market.v1.SoccerPenaltyShootoutAttempt
    gateway.market.v1.MarketGroupStat:
      type: object
      properties:
        marketGroupId:
          type: string
          description: >-
            Market group identifier this stat applies to (matches
            EventMarketGroup.id)
        line:
          type: number
          format: decimal
          description: Line value for the group
          nullable: true
        current:
          type: number
          format: decimal
          description: Current line value for the group
          nullable: true
    gateway.tags.v1.TagLeague:
      type: object
      properties:
        id:
          type: integer
          format: int32
        name:
          type: string
        sportId:
          type: integer
          format: int32
        tagId:
          type: integer
          format: int32
          nullable: true
        image:
          type: string
          nullable: true
        resolution:
          type: string
          nullable: true
        ordering:
          type: string
          nullable: true
        activeSeriesId:
          type: integer
          format: int32
          nullable: true
        isOperational:
          type: boolean
          nullable: true
        automaticResolution:
          type: boolean
          nullable: true
        createdAt:
          type: string
          nullable: true
        slug:
          type: string
        abbreviation:
          type: string
          nullable: true
    gateway.tags.v1.TagSport:
      type: object
      properties:
        id:
          type: integer
          format: int32
        name:
          type: string
        tagId:
          type: integer
          format: int32
          nullable: true
        createdAt:
          type: string
          nullable: true
        slug:
          type: string
        image:
          type: string
          nullable: true
    gateway.market.v1.SportsTeamProvider:
      type: object
      properties:
        provider:
          $ref: '#/components/schemas/gateway.market.v1.Provider'
        providerId:
          type: string
          description: The provider id
    gateway.market.v1.ResolvedColor:
      type: object
      properties:
        light:
          type: string
          description: Hex color for light mode
        dark:
          type: string
          description: Hex color for dark mode
    gateway.market.v1.GameUpdate:
      type: object
      properties:
        id:
          type: integer
          format: int32
          description: Game update ID
        eventId:
          type: integer
          format: int32
          description: Event ID
        sportradarGameId:
          type: string
          description: Sportradar game ID
        type:
          type: string
          description: Game update type
        title:
          type: string
          description: Game update title
        subtitle:
          type: string
          description: Game update subtitle
          nullable: true
        subject:
          type: string
          description: Game update subject
          nullable: true
        team:
          type: string
          description: Team name
          nullable: true
        period:
          type: string
          description: Game period
          nullable: true
        clock:
          type: string
          description: Game clock
          nullable: true
        highlightAt:
          type: string
          format: date-time
          description: Highlight timestamp
          nullable: true
        createdAt:
          type: string
          format: date-time
          description: Creation timestamp
          nullable: true
    gateway.market.v1.MarketSideType:
      type: string
      enum:
        - MARKET_SIDE_TYPE_ERC1155
        - MARKET_SIDE_TYPE_INSTRUMENT
    gateway.market.v1.CricketInnings:
      type: object
      properties:
        number:
          type: integer
          format: int32
          nullable: true
        battingTeamId:
          type: string
          nullable: true
        runs:
          type: integer
          format: int32
          nullable: true
        wickets:
          type: integer
          format: int32
          nullable: true
        oversCompleted:
          type: integer
          format: int32
          nullable: true
        complete:
          type: boolean
          nullable: true
        ballsIntoOver:
          type: integer
          format: int32
          nullable: true
    gateway.market.v1.CricketChase:
      type: object
      properties:
        target:
          type: integer
          format: int32
          nullable: true
        runsNeeded:
          type: integer
          format: int32
          nullable: true
        ballsRemaining:
          type: integer
          format: int32
          nullable: true
        currentRunRate:
          type: number
          format: double
          nullable: true
        requiredRunRate:
          type: number
          format: double
          nullable: true
    gateway.market.v1.SoccerPenaltyShootoutAttempt:
      type: object
      properties:
        competitorId:
          type: string
        status:
          $ref: >-
            #/components/schemas/gateway.market.v1.SoccerPenaltyShootoutAttemptStatus
        playerId:
          type: string
        playerName:
          type: string
    gateway.market.v1.Provider:
      type: string
      enum:
        - PROVIDER_SPORTSDATAIO
        - PROVIDER_SPORTRADAR
        - PROVIDER_OPTICODDS
        - PROVIDER_PANDASCORE
        - PROVIDER_INFRONT
        - PROVIDER_ENETPULSE
        - PROVIDER_UFC
    gateway.market.v1.SoccerPenaltyShootoutAttemptStatus:
      type: string
      enum:
        - SOCCER_PENALTY_SHOOTOUT_ATTEMPT_STATUS_NOT_TAKEN_YET
        - SOCCER_PENALTY_SHOOTOUT_ATTEMPT_STATUS_SCORED
        - SOCCER_PENALTY_SHOOTOUT_ATTEMPT_STATUS_MISSED

````