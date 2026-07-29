"""Layer 2: weather-aware modelling and (eventually) setpoint optimisation.

Talks to layer 1 only over MQTT and is allowed to fail. Today it estimates
and publishes; it does not command. See estimator.py for why that boundary is
structural rather than a matter of discipline.
"""
