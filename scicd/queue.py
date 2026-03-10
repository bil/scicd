"""
Google Cloud Pub/Sub queue management.
Provides low-level interaction with GCP for distributed task coordination.
"""

import json

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1

from scicd import config


class PubSubManager:
    """Handles publishing and pulling task data via GCP Pub/Sub."""

    def __init__(self, topic_id=None, subscription_id=None):
        """
        Initializes the Pub/Sub client.

        Args:
            topic_id (str): The GCP Pub/Sub topic ID.
            subscription_id (str): The GCP Pub/Sub subscription ID.
        """
        cfg = config.get_config()
        gcp_cfg = cfg["gcp"]
        project = gcp_cfg["project"]

        # Use provided IDs or fall back to global config
        topic = topic_id or gcp_cfg["pubsub_topic"]
        sub = subscription_id or gcp_cfg["pubsub_subscription"]

        self.publisher = pubsub_v1.PublisherClient() if topic else None
        self.subscriber = pubsub_v1.SubscriberClient() if sub else None

        self.topic_path = (
            self.publisher.topic_path(project, topic) if self.publisher else None
        )
        self.sub_path = (
            self.subscriber.subscription_path(project, sub) if self.subscriber else None
        )

    def publish_messages(self, messages):
        """
        Publishes a list of dictionaries to the configured topic.

        Args:
            messages (list): List of dictionaries to serialize and publish.
        """
        for msg in messages:
            data = json.dumps(msg).encode("utf-8")
            self.publisher.publish(self.topic_path, data)

    def pull_message(self, timeout=None):
        """
        Pulls a single message from the subscription.

        Args:
            timeout (int): Seconds to wait before timing out.

        Returns:
            tuple: (ack_id, data) if successful, (None, None) on timeout or empty queue.
        """
        try:
            response = self.subscriber.pull(
                request={"subscription": self.sub_path, "max_messages": 1},
                timeout=timeout,
            )
            if not response.received_messages:
                return None, None
            msg = response.received_messages[0]
            return msg.ack_id, json.loads(msg.message.data.decode("utf-8"))
        except DeadlineExceeded:
            return None, None

    def ack_message(self, ack_id):
        """
        Acknowledges a processed message to remove it from the queue.

        Args:
            ack_id (str): The acknowledgement ID from pull_message.
        """
        self.subscriber.acknowledge(
            request={"subscription": self.sub_path, "ack_ids": [ack_id]}
        )

    def drain_subscription(self):
        """
        Removes all pending messages from the subscription.
        """
        print(f"Draining: {self.sub_path}")
        while True:
            try:
                response = self.subscriber.pull(
                    request={"subscription": self.sub_path, "max_messages": 100},
                    timeout=2,
                )
                if not response.received_messages:
                    break
                ack_ids = [m.ack_id for m in response.received_messages]
                self.subscriber.acknowledge(
                    request={"subscription": self.sub_path, "ack_ids": ack_ids}
                )
            except DeadlineExceeded:
                break
