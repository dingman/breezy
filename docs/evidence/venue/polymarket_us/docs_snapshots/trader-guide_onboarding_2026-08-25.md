> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Onboarding

> Get started with the Polymarket Exchange API

<Note>**Individual traders:** You do not need to complete this onboarding process. Head to the [Retail Trading](/retail-api/overview) tab to get started.</Note>

## Step 1: Register

Create your account through the [Polymarket Institutional registration portal](https://institutional.polymarketexchange.com/register). The portal walks you through setting up the credentials you need to access the API across each environment (development, pre-production, and production).

### API-Specific Requirements

<AccordionGroup>
  <Accordion title="REST / gRPC">
    No additional setup is required beyond registering through the portal.
  </Accordion>

  <Accordion title="FIX">
    If you intend to use the FIX API, include your **AWS Account ID** during registration so that a VPC PrivateLink connection can be established.

    You should still complete registration even if FIX is your primary connectivity method, as it is required for full platform functionality.
  </Accordion>
</AccordionGroup>

## Step 2: Submit Your Onboarding Documents

Download and complete the required onboarding document, then submit it through the registration portal:

[Entity Participant Agreement](https://www.polymarketexchange.com/files/legal/Polymarket%20-%20Entity%20Participant%20and%20Clearing%20Member%20Agreement%20\(2026.05.20\).pdf)

## Step 3: Receive Your Credentials

The Polymarket team will review your submission and provide your Client ID credentials for both pre-production and production environments.

If you requested FIX connectivity, you will also receive your FIX connection details. See [FIX Connection Setup](/institutional/fix-api/fix-connection-setup) for VPC endpoint configuration and session setup.

## Step 4: Fund Your Account

Your pre-production account will be funded with dummy funds for testing purposes. To begin trading on the production environment, fund your account via wire transfer:

* [Inbound Wire Form](https://drive.google.com/uc?export=download\&id=1BJrmFYk1_RIZjj1tybNnqgRWJbdCNgr0) - Use this form to wire funds into your Polymarket account
* [Outbound Wire Form](https://drive.google.com/uc?export=download\&id=1X0fC4kZzEj9-_ZXcbAIEr4YH0QuQUNos) - Use this form to withdraw funds from your Polymarket account

Complete the appropriate form and follow the wire instructions provided. Funds are typically available for trading within 1-2 business days of receipt.
