# Distributed Real-Time Drawing Board with Mini-RAFT Consensus

**Team 8 – Cloud Computing Project**

## Team Members
- Sanjana Pulla – PES2UG23CS529  
- Sharon A – PES2UG23CS544  
- Shreya Parashar – PES2UG23CS561  
- Shrivadhu B J – PES2UG23CS568  

## Project Overview
This project implements a **distributed real-time drawing board** where multiple users can draw on a shared browser canvas. Drawing strokes appear instantly for all connected clients.

The backend consists of **three replica nodes** that maintain a shared log of strokes using a **Mini-RAFT consensus protocol** to ensure consistency and fault tolerance.

A **Gateway service** manages WebSocket connections, forwards drawing events to the current leader replica, and broadcasts committed updates to all connected clients.


## Key Components
- **Frontend** – Browser-based drawing canvas  
- **Gateway** – WebSocket server managing client connections  
- **Replicas** – Implement Mini-RAFT leader election and log replication  
- **Docker** – Containerized deployment using Docker Compose  

## Goal
Build a **fault-tolerant distributed system** that maintains consistent drawing state across replicas, even during replica failures or restarts.s